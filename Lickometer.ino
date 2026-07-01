// lickometer_risha_final.ino
// Lickometer V0.1 AIC Columbia University RHormigo 2025
// Modified: all terminal interaction removed.
// Control comes entirely from the Python GUI via serial commands.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// COMMANDS  (sent by Python GUI as a newline-terminated string):
//
//   r          Start streaming events
//   s          Stop  streaming events
//   iNNNNN     Set weight-report interval in seconds (10–99999)
//              NOTE: load-cell rate is now set by LOADCELL_PERIOD_MS in the config
//              block below, NOT by this command. Kept only so the GUI won't error.
//   wNNNNN     Set gain-cal averaging window in ms (100–60000)
//   o          Offset calibration  (all channels, bottles empty)
//   Nko        Offset calibration  (channel N only, 0-7)
//   cg         Gain   calibration  (all channels, 50g on each)
//   kNg        Gain   calibration  (channel N only, 0-7)
//   t          Touch sensor calibration
//   sN         Begin setting threshold for channel N (0-7)
//              → next line received is the integer value (20-255)
//
// STREAMING OUTPUT  (one line per event):
//   timestamp_ms,id,amplitude
//
//   id 0-7   = load cell reading in grams
//              0=brd0-right  1=brd0-left  2=brd1-right … 7=brd3-left
//   id 8-15  = lick ONSET   (channels 0-7, id = 8+ch)
//   id 16-23 = lick OFFSET  (channels 0-7, id = 16+ch)
//
//   amplitude = grams for load cells, 1 for onset, 0 for offset
//
// Comment/header lines begin with '#' and are ignored by the Python parser.
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#include "Lickometer.h"
#include <Arduino.h>
#include <Wire.h>
#include "QTouchSeeedRH.h"
#include "ADS1256.h"
#include <PWFusion_TCA9548A.h>
#include <EEPROM.h>

// ── Pin definitions ──────────────────────────────────────────────────────────
#define LED   13
#define CS_0   8
#define CS_1   9
#define CS_2  10
#define CS_3  11
#define DRY_0  3
#define DRY_1  4
#define DRY_2  5
#define DRY_3  6
#define PDWN   7
#define RESET  0

// ── I²C multiplexer addresses (Brd0-3 = 114-117) ────────────────────────────
const uint8_t i2cMuxAdr[] = {114, 115, 116, 117};
const uint8_t diffList[]  = {DIFF_0_1, DIFF_2_3};

// ── ADC pin sets ──────────────────────────────────────────────────────────────
struct ADS1256_Pins { const byte dry, reset, pdwn, cs; };
const ADS1256_Pins pinSets[4] = {
    {DRY_0, RESET, PDWN, CS_0},
    {DRY_1, RESET, PDWN, CS_1},
    {DRY_2, RESET, PDWN, CS_2},
    {DRY_3, RESET, PDWN, CS_3}
};

// ── Calibration storage ───────────────────────────────────────────────────────
struct { uint8_t OFC0, OFC1, OFC2; float FSC; } CALSys[4][2];
#define CALSysSize sizeof(CALSys[0][0])

uint8_t touchTH[8];        // Per-channel touch threshold

ADS1256*     adcAmp[4];
SeeedQTouch  QTouch[4];
TCA9548A     i2cMux[4];

uint8_t  BCHi[2]   = {2, 1}; // Inverted channel index to match hardware
uint32_t interval  = 1;     // Weight-report interval in seconds (legacy; no longer
                            // gates load-cell output — see config block below)
uint32_t gainAvgMs = 2000;   // C4: gain-cal averaging window (ms) — avoids snap jumps

// ── Load-cell streaming rate config ───────────────────────────────────────────
// Output rate is set here, NOT by the `i`/interval command. Tune and re-upload.
//
//   LOADCELL_DRATE      ADS1256 data rate (single tuning point). Lower = less
//                       noise, longer settle: DRATE_100SPS ≈ 10 ms, DRATE_50SPS
//                       ≈ 20 ms, DRATE_5SPS ≈ 200 ms (old). Settling after a
//                       channel switch is now handled in the library (setMUX
//                       issues SYNC+WAKEUP), so this stays correct at any rate.
//
//   LOADCELL_PERIOD_MS  Spacing between consecutive emitted values. One channel
//                       is read per tick, cycling 0->7 (round-robin). 150 -> a
//                       new value every 150 ms (matches the 100-200 ms goal); a
//                       full 8-channel sweep takes 8 x this. Lower it for faster
//                       output now that the per-read time is only ~10-15 ms.
//
//   LOADCELL_SETTLE_MS  Extra settle after the MUX switch. Leave at 0 — the
//                       library's SYNC+WAKEUP already guarantees a settled read.
#define LOADCELL_DRATE       DRATE_5SPS
#define LOADCELL_PERIOD_MS   150
#define LOADCELL_SETTLE_MS   0
//   LOADCELL_DISCARD    Number of conversions to read-and-throw-away after a
//                       channel switch + offset load, before keeping a value.
//                       After a SYNC (issued by setMUX) the filter is reset, so
//                       1 is enough at DRATE_5SPS. RAISE to 2 if you increase the
//                       data rate and see the first post-switch sample biased.
#define LOADCELL_DISCARD     1

// ── State ─────────────────────────────────────────────────────────────────────
bool     streaming            = false;
bool     touchState[8]        = {false};
bool     awaitingThreshValue  = false;  // true after "sN" while we wait for the value
int8_t   threshChannel        = -1;     // which channel we're setting threshold for

// ── Non-blocking load-cell read state machine ─────────────────────────────────
// The load-cell ADC (slow at low DRATE) and the lick/touch sensors are read by
// the SAME single-threaded loop. The old code read a load cell with a blocking
// call that stalled the loop ~400 ms at DRATE_5SPS, during which touch was never
// sampled — so quick licks were missed. This state machine never blocks on the
// ADC: it kicks off a conversion, then polls DRDY each loop pass and only pulls
// the value once it's ready, so updateTouch() runs continuously regardless of
// the load-cell data rate. The two detections are now fully independent.
enum LCState { LC_IDLE, LC_WAIT };
LCState  lcState        = LC_IDLE;
uint8_t  lcCh           = 0;            // round-robin load-cell channel 0-7
uint8_t  lcDiscardLeft  = 0;            // settling conversions still to discard
uint32_t lcStartMs      = 0;           // for a dead-amp timeout

// ── Helpers ───────────────────────────────────────────────────────────────────

void readFlush() {
    while (Serial.available()) Serial.read();
}

int readLine(char *buf, int maxLen) {
    int len = 0;
    while (true) {
        while (!Serial.available()) {}
        char c = Serial.read();
        if (c == '\r' || c == '\n') {
            while (Serial.available()) {
                char nx = Serial.peek();
                if (nx == '\r' || nx == '\n') Serial.read();
                else break;
            }
            buf[len] = '\0';
            return len;
        }
        if (len < maxLen - 1) buf[len++] = c;
    }
}

// Emit one event line: timestamp_ms,id,amplitude
void emitEvent(uint8_t id, float amp) {
    Serial.print(millis());
    Serial.print(',');
    Serial.print(id);
    Serial.print(',');
    Serial.println(amp, 1);
}

// C4: average the load-cell voltage over `ms` milliseconds (many ADC reads) so
// the gain calibration isn't thrown off by a single noisy sample / voltage jump.
float avgVoltage(uint8_t brd, uint32_t ms) {
    double   sum = 0.0;
    uint32_t n   = 0;
    uint32_t t0  = millis();
    do {
        sum += adcAmp[brd]->convertToVoltage(adcAmp[brd]->readSingle());
        n++;
    } while (millis() - t0 < ms);
    return n ? (float)(sum / n) : 0.0f;
}

// Settled, offset-correct single-cell read. Reproduces the OLD firmware's proven
// sequence and is the single path all weight reads go through:
//   1) switch channel (setMUX issues SYNC+WAKEUP -> resets the SINC filter),
//   2) load THIS channel's offset bytes (OFC is SHARED per chip across the two
//      differential cells, so it MUST be reloaded on every read),
//   3) discard LOADCELL_DISCARD settled conversion(s) so the kept sample is taken
//      after the channel has settled with the final OFC applied,
//   4) read + convert with the per-channel software full-scale (FSC).
float readGrams(uint8_t brd, uint8_t brdCH) {
    adcAmp[brd]->setMUX(diffList[brdCH]);
    adcAmp[brd]->writeRegister(OFC0_REG, CALSys[brd][brdCH].OFC0);
    adcAmp[brd]->writeRegister(OFC1_REG, CALSys[brd][brdCH].OFC1);
    adcAmp[brd]->writeRegister(OFC2_REG, CALSys[brd][brdCH].OFC2);
    for (uint8_t d = 0; d < LOADCELL_DISCARD; d++)
        adcAmp[brd]->readSingle();                 // discard settling conversion(s)
    long raw = adcAmp[brd]->readSingle();          // keep: settled + offset-correct
    return adcAmp[brd]->convertToVoltage(raw) * 28571.429f * CALSys[brd][brdCH].FSC;
}

// Non-blocking equivalent of readGrams for the streaming loop. Advances the
// load-cell read by at most one tiny step per call and returns immediately,
// so the caller can keep sampling touch every loop pass. Same read sequence as
// readGrams (setMUX -> load OFC -> discard settling -> keep), just spread across
// many loop iterations instead of blocking through it.
void serviceLoadCells() {
    static uint32_t lastWeightTime = 0;
    uint8_t brd   = lcCh >> 1;
    uint8_t brdCH = lcCh & 1;

    switch (lcState) {
    case LC_IDLE:
        // Wait until it's time to start the next channel, then kick off a
        // conversion. setMUX issues SYNC+WAKEUP (resets the filter and starts a
        // fresh conversion); writing OFC + setMUX is fast (microseconds).
        if (millis() - lastWeightTime < LOADCELL_PERIOD_MS) return;
        lastWeightTime = millis();
        adcAmp[brd]->setMUX(diffList[brdCH]);
        adcAmp[brd]->writeRegister(OFC0_REG, CALSys[brd][brdCH].OFC0);
        adcAmp[brd]->writeRegister(OFC1_REG, CALSys[brd][brdCH].OFC1);
        adcAmp[brd]->writeRegister(OFC2_REG, CALSys[brd][brdCH].OFC2);
        lcDiscardLeft = LOADCELL_DISCARD;
        lcStartMs     = millis();
        lcState       = LC_WAIT;
        return;

    case LC_WAIT:
        // Poll DRDY WITHOUT blocking. If the conversion isn't ready yet, return
        // now so the loop goes straight back to updateTouch().
        if (digitalRead(pinSets[brd].dry) == HIGH) {
            // Dead-amp safety: if a board never asserts DRDY, skip it instead of
            // stalling the round-robin (touch keeps running regardless).
            if (millis() - lcStartMs > 1000UL) {
                lcCh    = (lcCh + 1) & 0x07;
                lcState = LC_IDLE;
            }
            return;
        }
        // DRDY low -> a conversion is ready; readSingle() returns immediately.
        {
            long raw = adcAmp[brd]->readSingle();
            if (lcDiscardLeft > 0) {
                lcDiscardLeft--;        // throw away settling conversion, keep waiting
                return;
            }
            float grams = adcAmp[brd]->convertToVoltage(raw)
                          * 28571.429f * CALSys[brd][brdCH].FSC;
            emitEvent(lcCh, grams);
            lcCh    = (lcCh + 1) & 0x07; // advance round-robin
            lcState = LC_IDLE;
        }
        return;
    }
}

// Callback for ADS library: keep sampling touch during long ADC waits
void delayWTouch(int16_t del) {
    for (; del > 0; del -= 20) {
        updateTouch();
        delay(10);
    }
}

// Sample all 8 touch channels; emit onset (id 8-15) or offset (id 16-23)
void updateTouch() {
    for (int8_t brd = 3; brd >= 0; brd--) {
        i2cMux[brd].setChannel(CHAN0);
        for (uint8_t brdCH = 0; brdCH < 2; brdCH++) {
            uint8_t ch      = (uint8_t)(brd << 1) + brdCH;
            bool    nowTouch = QTouch[brd].isTouch(BCHi[brdCH]);

            if (nowTouch && !touchState[ch]) {
                touchState[ch] = true;
                if (streaming) emitEvent(8 + ch, 1);   // onset
                digitalWrite(LED, HIGH);
            } else if (!nowTouch && touchState[ch]) {
                touchState[ch] = false;
                if (streaming) emitEvent(16 + ch, 0);  // offset
                digitalWrite(LED, LOW);
            }
        }
        i2cMux[brd].setChannel(CHAN_NONE);
    }
}

void valCfg(uint8_t brd) {
    if ((adcAmp[brd]->readRegister(ADCON_REG) & 0x07) == 0 ||
         adcAmp[brd]->readRegister(DRATE_REG) == DRATE_30000SPS) {
        adcAmp[brd]->setPGA(PGA_64);
        adcAmp[brd]->setDRATE(LOADCELL_DRATE);
    }
}

// ── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    pinMode(LED, OUTPUT);
    Wire.begin();
    Wire.setTimeout(1000);
    Serial.begin(115200);
    while (!Serial);

    Serial.println(F("# Lickometer Columbia AIC V0.1"));
    Serial.println(F("# Awaiting commands from Python GUI."));

    // Recover calibration from EEPROM
    EEPROM.get(0,   CALSys);
    EEPROM.get(96,  interval);
    EEPROM.get(100, touchTH);
    EEPROM.get(108, gainAvgMs);                       // C4: gain averaging window (ms)

    // Init touch sensors
    for (uint8_t i = 4; i--;) {
        i2cMux[i].begin(i2cMuxAdr[i]);
        i2cMux[i].setChannel(CHAN0);
        QTouch[i].setMaxDuration(62);
        QTouch[i].setNTHRForKey(touchTH[i << 1],       1);
        QTouch[i].setNTHRForKey(touchTH[(i << 1) + 1], 2);
        QTouch[i].calibrate();
        QTouch[i].setGroup(0, 0);
        QTouch[i].setGroup(1, 0);
        QTouch[i].setGroup(2, 0);
        i2cMux[i].setChannel(CHAN_NONE);
    }

    // Init ADCs
    for (uint8_t i = 4; i--;) {
        adcAmp[i] = new ADS1256(pinSets[i].dry, pinSets[i].reset,
                                 pinSets[i].pdwn, pinSets[i].cs, 2.500);
        // (No setCallback: this library has no touch-during-delay callback. It is
        //  unnecessary now anyway — the long library delays are gone, and the
        //  round-robin loop samples touch every pass via updateTouch().)
        adcAmp[i]->InitializeADC();
        adcAmp[i]->setPGA(PGA_64);
        adcAmp[i]->setDRATE(LOADCELL_DRATE);
        digitalWrite(LED, 1);
        adcAmp[i]->writeRegister(FSC0_REG, 0x4C);
        adcAmp[i]->writeRegister(FSC1_REG, 0xE1);
        adcAmp[i]->writeRegister(FSC2_REG, 0x2E);
        adcAmp[i]->sendDirectCommand(SELFOCAL);
        adcAmp[i]->waitForLowDRDY();
        digitalWrite(LED, 0);
    }

    Serial.println(F("# Ready."));
    if (interval < 1 || interval > 99999) interval = 30;
    if (gainAvgMs < 100 || gainAvgMs > 60000) gainAvgMs = 2000;   // C4 default 2 s
}

// ── Loop ─────────────────────────────────────────────────────────────────────

void loop() {
    // ── Command handling ──────────────────────────────────────────────────────
    if (Serial.available() > 0) {
        char cmd[8];
        int  cmdLen = readLine(cmd, sizeof(cmd));
        if (cmdLen == 0) { readFlush(); return; }

        // If we're waiting for a threshold value after an "sN" command
        if (awaitingThreshValue) {
            int val = atoi(cmd);
            if (val >= 20 && val <= 255 && threshChannel >= 0) {
                touchTH[threshChannel] = (uint8_t)val;
                EEPROM.update(100 + threshChannel, touchTH[threshChannel]);
                i2cMux[threshChannel >> 1].setChannel(CHAN0);
                QTouch[threshChannel >> 1].setNTHRForKey(
                    touchTH[threshChannel], (threshChannel & 1) + 1);
                i2cMux[threshChannel >> 1].setChannel(CHAN_NONE);
                Serial.print(F("# Threshold ch"));
                Serial.print(threshChannel);
                Serial.print(F(" set to "));
                Serial.println(val);
            } else {
                Serial.println(F("# Bad threshold value (20-255 required)"));
            }
            awaitingThreshValue = false;
            threshChannel       = -1;
            readFlush();
            return;
        }

        char firstChar = cmd[0];

        // ── 'r' — start streaming ────────────────────────────────────────────
        if (firstChar == 'r' && cmdLen == 1) {
            if (!streaming) {
                streaming = true;
                for (uint8_t i = 0; i < 8; i++) touchState[i] = false;
                lcState = LC_IDLE; lcCh = 0; lcDiscardLeft = 0;  // fresh round-robin
                Serial.println(F("# timestamp_ms,id,amplitude"));
                Serial.println(F("# id 0-7=load(g) | 8-15=onset | 16-23=offset"));
            }
            readFlush();
            return;
        }

        // ── 's' (alone) — stop streaming ────────────────────────────────────
        if (firstChar == 's' && cmdLen == 1) {
            streaming = false;
            Serial.println(F("# Stream stopped."));
            readFlush();
            return;
        }

        // ── 'sN' — set threshold for channel N ──────────────────────────────
        if (firstChar == 's' && cmdLen == 2) {
            int8_t ch = cmd[1] - '0';
            if (ch >= 0 && ch <= 7) {
                threshChannel       = ch;
                awaitingThreshValue = true;
                // Python will send the value as the next line
            } else {
                Serial.println(F("# Bad channel (0-7)"));
            }
            readFlush();
            return;
        }

        // ── 'iNNNNN' — set interval ──────────────────────────────────────────
        if (firstChar == 'i' && cmdLen > 1) {
            long n = atol(cmd + 1);
            if (n >= 10 && n <= 99999) {
                interval = (uint32_t)n;
                EEPROM.put(96, interval);
                Serial.print(F("# Interval set to "));
                Serial.println(interval);
            } else {
                Serial.println(F("# Bad interval (10-99999)"));
            }
            readFlush();
            return;
        }

        // ── 'wNNNNN' — set gain-cal averaging window in ms (100–60000) ─────────
        if (firstChar == 'w' && cmdLen > 1) {
            long n = atol(cmd + 1);
            if (n >= 100 && n <= 60000) {
                gainAvgMs = (uint32_t)n;
                EEPROM.put(108, gainAvgMs);
                Serial.print(F("# Gain averaging window set to "));
                Serial.print(gainAvgMs);
                Serial.println(F(" ms"));
            } else {
                Serial.println(F("# Bad window (100-60000 ms)"));
            }
            readFlush();
            return;
        }

        // ── 'o' — offset calibration (all channels) ──────────────────────────
        if (firstChar == 'o' && cmdLen == 1) {
            Serial.println(F("# Offset calibration starting…"));
            for (uint8_t brd = 4; brd--;) {
                for (uint8_t brdCH = 2; brdCH--;) {
                    adcAmp[brd]->setMUX(diffList[brdCH]);
                    for (uint8_t d = 0; d < LOADCELL_DISCARD; d++)
                        adcAmp[brd]->readSingle();   // settle the channel before SYSOCAL
                    adcAmp[brd]->sendDirectCommand(SYSOCAL);
                    adcAmp[brd]->waitForLowDRDY();
                    CALSys[brd][brdCH].OFC0 = adcAmp[brd]->readRegister(OFC0_REG);
                    CALSys[brd][brdCH].OFC1 = adcAmp[brd]->readRegister(OFC1_REG);
                    CALSys[brd][brdCH].OFC2 = adcAmp[brd]->readRegister(OFC2_REG);
                    EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH),     CALSys[brd][brdCH].OFC0);
                    EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) + 1, CALSys[brd][brdCH].OFC1);
                    EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) + 2, CALSys[brd][brdCH].OFC2);
                }
            }
            Serial.println(F("# Offset calibration done."));
            readFlush();
            return;
        }

        // ── 'cg' — gain calibration (all channels) ────────────────────────────
        if (firstChar == 'c' && cmdLen == 2 && cmd[1] == 'g') {
            Serial.println(F("# Gain calibration (all channels) starting…"));
            for (int8_t ch = 7; ch >= 0; ch--) {
                uint8_t brd   = ch >> 1;
                uint8_t brdCH = ch &  1;
                adcAmp[brd]->setMUX(diffList[brdCH]);
                adcAmp[brd]->writeRegister(OFC0_REG, CALSys[brd][brdCH].OFC0);
                adcAmp[brd]->writeRegister(OFC1_REG, CALSys[brd][brdCH].OFC1);
                adcAmp[brd]->writeRegister(OFC2_REG, CALSys[brd][brdCH].OFC2);
                for (uint8_t d = 0; d < LOADCELL_DISCARD; d++)
                    adcAmp[brd]->readSingle();   // settle with final OFC before averaging
                CALSys[brd][brdCH].FSC =
                    50.0f / (avgVoltage(brd, gainAvgMs) * 28571.429f);
                EEPROM.put(CALSysSize * ch + 3, CALSys[brd][brdCH].FSC);
                Serial.print(F("# ch"));
                Serial.print(ch);
                Serial.print(F(" FSC="));
                Serial.println(CALSys[brd][brdCH].FSC, 4);
            }
            Serial.println(F("# Gain calibration done."));
            readFlush();
            return;
        }

        // ── 'kNg' — gain calibration (single channel N) ───────────────────────
        if (firstChar == 'k' && cmdLen == 3 && cmd[2] == 'g') {
            int8_t ch = cmd[1] - '0';
            if (ch >= 0 && ch <= 7) {
                uint8_t brd   = ch >> 1;
                uint8_t brdCH = ch &  1;
                adcAmp[brd]->setMUX(diffList[brdCH]);
                adcAmp[brd]->writeRegister(OFC0_REG, CALSys[brd][brdCH].OFC0);
                adcAmp[brd]->writeRegister(OFC1_REG, CALSys[brd][brdCH].OFC1);
                adcAmp[brd]->writeRegister(OFC2_REG, CALSys[brd][brdCH].OFC2);
                for (uint8_t d = 0; d < LOADCELL_DISCARD; d++)
                    adcAmp[brd]->readSingle();   // settle with final OFC before averaging
                CALSys[brd][brdCH].FSC =
                    50.0f / (avgVoltage(brd, gainAvgMs) * 28571.429f);
                EEPROM.put(CALSysSize * ch + 3, CALSys[brd][brdCH].FSC);
                Serial.print(F("# ch"));
                Serial.print(ch);
                Serial.print(F(" FSC="));
                Serial.println(CALSys[brd][brdCH].FSC, 4);
                Serial.println(F("# Gain calibration done."));
            } else {
                Serial.println(F("# Bad channel (0-7)"));
            }
            readFlush();
            return;
        }

        // ── 'Nko' — offset calibration (single channel N) ─────────────────────
        if (cmdLen == 3 && cmd[1] == 'k' && cmd[2] == 'o'
            && cmd[0] >= '0' && cmd[0] <= '7') {
            int8_t ch = cmd[0] - '0';
            uint8_t brd   = ch >> 1;
            uint8_t brdCH = ch &  1;
            adcAmp[brd]->setMUX(diffList[brdCH]);
            for (uint8_t d = 0; d < LOADCELL_DISCARD; d++)
                adcAmp[brd]->readSingle();   // settle the channel before SYSOCAL
            adcAmp[brd]->sendDirectCommand(SYSOCAL);
            adcAmp[brd]->waitForLowDRDY();
            CALSys[brd][brdCH].OFC0 = adcAmp[brd]->readRegister(OFC0_REG);
            CALSys[brd][brdCH].OFC1 = adcAmp[brd]->readRegister(OFC1_REG);
            CALSys[brd][brdCH].OFC2 = adcAmp[brd]->readRegister(OFC2_REG);
            EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH),     CALSys[brd][brdCH].OFC0);
            EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) + 1, CALSys[brd][brdCH].OFC1);
            EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) + 2, CALSys[brd][brdCH].OFC2);
            Serial.print(F("# ch"));
            Serial.print(ch);
            Serial.println(F(" offset calibration done."));
            readFlush();
            return;
        }

        // ── 't' — touch calibration ───────────────────────────────────────────
        if (firstChar == 't' && cmdLen == 1) {
            for (uint8_t i = 4; i--;) {
                i2cMux[i].setChannel(CHAN0);
                QTouch[i].calibrate();
                i2cMux[i].setChannel(CHAN_NONE);
                delay(10);
            }
            Serial.println(F("# Touch calibration done."));
            readFlush();
            return;
        }

        Serial.print(F("# Unknown command: "));
        Serial.println(cmd);
        readFlush();
    }

    // ── Streaming loop ────────────────────────────────────────────────────────
    if (streaming) {
        // Load cells: non-blocking. Advances at most one tiny step, returning
        // immediately when the next ADC conversion isn't ready yet.
        serviceLoadCells();

        // Touch: sampled EVERY loop pass, independent of the load-cell rate, so
        // even a quick brush is caught. This is the fix for the low-sensitivity
        // (only-registers-on-squeeze) behavior.
        updateTouch();
    }
}
