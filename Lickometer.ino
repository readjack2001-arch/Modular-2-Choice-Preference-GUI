//Lickometer V0.1 AIC Columbia University RHormigo 2025
#include "Lickometer.h"
#include <Arduino.h>
#include <Wire.h>
#include "QTouchSeeedRH.h"
#include "ADS1256.h"
#include <PWFusion_TCA9548A.h>
#include <EEPROM.h>


//ADCs PIN OUT
#define LED  13
#define CS_0  8
#define CS_1  9
#define CS_2  10
#define CS_3  11
#define DRY_0  3
#define DRY_1  4
#define DRY_2  5
#define DRY_3  6
#define PDWN 7
#define RESET 0



//Mux addresses: Brd0=114(b010) Brd1=115(b011) Brd2=116(b100) Brd3=117(b101)

const uint8_t i2cMuxAdr[] = {114,115,116,117}; 

const uint8_t diffList[]{DIFF_0_1,DIFF_2_3 };

//Create array of sets of pins for 4 ADCs
struct ADS1256_Pins {
    const byte dry;
    const byte reset;
    const byte pdwn;
    const byte cs;
};
const ADS1256_Pins pinSets[4] = {
  {DRY_0, RESET, PDWN, CS_0},
  {DRY_1, RESET, PDWN, CS_1},
  {DRY_2, RESET, PDWN, CS_2},
  {DRY_3, RESET, PDWN, CS_3}
};

struct {
    uint8_t OFC0;  //Offset Calibration byte 0
    uint8_t OFC1;  //Offset Calibration byte 1
    uint8_t OFC2;  //Offset Calibration byte 2
    float FSC;     //Full Scale Calibration value
}CALSys[4][2];   //Calibration Settings CALsys[Board][Channel]
#define  CALSysSize sizeof(CALSys[0][0])  //For indexing (In arduino this is 7 bytes, unpadded by default)
uint8_t touchTH[8];  //Lick touch threshold for channels 0 to 7, initial is set with 120


ADS1256* adcAmp[4];  //Array of 4 ADCs, boards 0 to 3

//Touch Sensor detectors
SeeedQTouch QTouch[4];
//Active touch Selectors
TCA9548A i2cMux[4];

bool doOnce[8] = { false }; //Just to do only once flags (used by 'l' debug command)
uint32_t T[8] = { 0 }; //Time length of licks (used by 'l' debug command)
uint32_t lickCnt[8] = { 0 }; //Lick Counts (used by 'l' debug command)
uint32_t lickAvg[8] = { 0 }; //Averaging lick lengths (used by 'l' debug command)
uint32_t interval; // Time in S that the r command reports weights, set with i command before run
uint8_t BCHi[2] = { 2, 1 };  //Inverted channel to match hardware

// --- Event streaming state (for the 'r' run) ---
bool streaming = false;          // true only while 'r' is streaming; gates event output
bool touchState[8] = { false };  // current touch state per station, for onset/offset edges

void helpSumary() {
  Serial.println(F("Lickometer Columbia AIC V0.1" \
  "\n---------------------------------------------------------------------------------------\n"
  "Run (r) streams events as: timestamp_ms , id , amplitude\n" \
  "   id 0-7 = weight in g | id 8-15 = lick onset | id 16-23 = lick offset\n" \
  "\tSend i <enter> to see weight-report interval, or set with iSSSSS <enter> (10 to 99999 Sec)\n" \
  "\tSend r <enter> to run, s to stop when running\n" \
  "\tSend sX <enter> to access to lick threshold, where X is channel 0 to 7. As s7 to for channel 7.\n" \
  "\t   Next <enter> to read current threshold setting, or TTT<enter> where TTT is a 10 to 255 setting\n" \
  "\tSend o <enter> to calibrate offset (to 0g)\n" \
  "\tSend c <enter> to calibrate gain (to 50g ref), follow instructions\n" \
  "\tSend kX <enter> to calibrate gain at X channel 0 to 7. As c7 to calibrate ch.7\n" \
  "\tSend t <enter> to calibrate touch sensor\n" \
  "\tSend h <enter> to print this again\n" \
  "---------------------------------------------------------------------------------------")); 
} 



void readFlush() {
    while (Serial.available()) {
        Serial.read();
    }
}

int readLine(char *buffer, int maxLen)
{
    int len = 0;

    while (true)
    {
        while (!Serial.available()) {}

        char c = Serial.read();

        if (c == '\r' || c == '\n')
        {
            while (Serial.available())
            {
                char next = Serial.peek();
                if (next == '\r' || next == '\n')
                    Serial.read();
                else
                    break;
            }

            buffer[len] = '\0';
            return len;
        }

        if (len < maxLen - 1)
            buffer[len++] = c;
    }
}


void setup()
{
  pinMode(LED, OUTPUT);

  Wire.begin();
  Wire.setTimeout(1000);
  Serial.begin(115200); 
  while (!Serial); //serial resetting

  helpSumary();
  Serial.println("Initializing Weight Amps and Touch Sensors...");

  //Recover last calibration offsets and gains from EEPROM
  EEPROM.get(0, CALSys);     //Get last calibration from EEPROM
  EEPROM.get(96, interval);  //Get last interval from EEPROM
  EEPROM.get(100, touchTH);  // Get last lick touch thresholds
 
  // Init 4 touch sensor and selector. Must be done before the amps to avoid crash due to callback calling I2C
  for (uint8_t i = 4; i--;) {
    //Touch sensors initialization of 4 sensors using 2 channels each. By selection of front Mux working as a switch in a parallel bus
    //this was developed this way to minimize wiring along the mice cages
    i2cMux[i].begin(i2cMuxAdr[i]);
    i2cMux[i].setChannel(CHAN0); //Turn on QTouch[i] with MUX , otherwise should be 0 (disconnected)
    QTouch[i].setMaxDuration(62);//the value determines how long any key can be in touch before it re-calibrates itself.160ms * 62 = 9.92s.
    QTouch[i].setNTHRForKey(touchTH[i<<1], 1);  //130 //set the threshold value for key1 to register a detection.This Value should not be less than 20.
    QTouch[i].setNTHRForKey(touchTH[(i<<1)+1], 2);  //set the threshold value for key2 
    QTouch[i].calibrate();
    QTouch[i].setGroup(0, 0);  //Touch Guard non blocking
    QTouch[i].setGroup(1, 0);  //1st Touch Key non blocking
    QTouch[i].setGroup(2, 0);  //2nd Touch Key non blocking
    i2cMux[i].setChannel(CHAN_NONE); //Turn off QTouch[i] so doesn't short multiple I2C branches together  
  } 
  Serial.println("Touch sensors ready...");
 //Init all 4 ADCs
  for (uint8_t i = 4; i--;) {
    //Initializing ACD Amps. They need Arduino pins for each: DRDY_x, RESET, PDWN, CS_x, VREF(float). 
    adcAmp[i] = new ADS1256(pinSets[i].dry, pinSets[i].reset, pinSets[i].pdwn, pinSets[i].cs, 2.500);
    adcAmp[i]->setCallback(delayWTouch); //pass pointer for callback purposes from slow ADS library
    adcAmp[i]->InitializeADC();
    adcAmp[i]->setPGA(PGA_64);
    adcAmp[i]->setDRATE(DRATE_5SPS);
   // Serial.println("T");
    digitalWrite(LED, 1);
    //Ideal FS default Gain for PGA64. Note that gain auto calibration is not used in ADC, instead is made externally 
    adcAmp[i]->writeRegister(FSC0_REG, 0x4C); 
    adcAmp[i]->writeRegister(FSC1_REG, 0xE1); 
    adcAmp[i]->writeRegister(FSC2_REG, 0x2E); 
    adcAmp[i]->sendDirectCommand(SELFOCAL);  //Internal offset
    adcAmp[i]->waitForLowDRDY();
    digitalWrite(LED, 0);

  }

  Serial.println("Amps ready...");  


  //Remove this after debug
  for (uint8_t i = 0; i < 4;  i++) {
      //Read back the above 3 initial debugging
      Serial.print("---------------------\nVerify Ch ");
      Serial.println(i);
      Serial.print("PGA: ");
      Serial.println(adcAmp[i]->readRegister(ADCON_REG) & 0x07);
      Serial.print("MUX: 0x");
      Serial.println(adcAmp[i]->readRegister(MUX_REG), HEX);
      Serial.print("DRATE: ");
      Serial.println(adcAmp[i]->readRegister(DRATE_REG));
  }
  Serial.println("---------------------\n");

}
bool prompt = false;
void loop()
{
   if (!prompt) {
       Serial.println("Ready>");
       prompt = true;
   }
  if (Serial.available() > 0)
  {
    uint8_t commandCharacter = Serial.read(); //we use characters (letters) for controlling the switch-case
    uint32_t cTime;  //Timer for run
    int8_t ch, cmdLen;
    char cmd[7];
   
    //Commands s to stop, r to run, c to calibrate(to 0g)
    //         t to calibrate touch sensor, h to print this again
    switch (commandCharacter) //based on the command character, we decide what to do
    {
        case 'c': //Perform a full Scale gain system  calibration on all weight cells Channels 0 to 7 sequentially
            Serial.println("\nGain Calibration for all channels.");            
            Serial.println("This expects no bottles and a weight standard of 50g in each channel.");
            Serial.println("If all eight 50g calibration standards are in place, enter g to go, or enter to cancel.");
            delay(5);  //wait to receive any other char in serial
            readFlush(); //flush CR, LF, or anything else. 
            while (Serial.available() == 0);
            if (Serial.read() == 'g') {
                readFlush(); 
                for (ch = 8; ch--;) {
                    adcAmp[ch >> 1]->setMUX(diffList[ch & 1]); //Select Mux channel 0 or 1 for corresponding board 
                    delay(200);
                    //Apply offset correction before read
                    adcAmp[ch >> 1]->writeRegister(OFC0_REG, CALSys[ch >> 1][ch & 1].OFC0);
                    adcAmp[ch >> 1]->writeRegister(OFC1_REG, CALSys[ch >> 1][ch & 1].OFC1);
                    adcAmp[ch >> 1]->writeRegister(OFC2_REG, CALSys[ch >> 1][ch & 1].OFC2);
                    CALSys[ch >> 1][ch & 1].FSC = 50.0 / (adcAmp[ch >> 1]->convertToVoltage(adcAmp[ch >> 1]->readSingle()) * 28571.429); //Error ratio to 50g
                    EEPROM.put(CALSysSize * ch + 3, CALSys[ch >> 1][ch & 1].FSC);
                    Serial.print("Amp ");
                    Serial.print(ch);
                    Serial.print(" Gain Calibrated with factor: ");
                    Serial.println(CALSys[ch >> 1][ch & 1].FSC, 4);
                }
                Serial.println("Gain Calibration DOne!");
                break;
            }
            Serial.println("Gain Calibration Canceled!");
            readFlush();
        break;
        case 'k': //Perform a full Scale gain system  calibration on a specific weight cells Channels 0 to 7
          Serial.print("\nGain Calibration for channel ");
          delay(5);  //wait to receive second char in serial
          ch = Serial.read() - '0';//receive and convert to integer
          if (ch < 0 || ch > 7) { //validate channel
              Serial.println(". \nUse kn where n is channel 0 to 7, ex. k2 and enter.");
              readFlush();
              break;
          }
          readFlush(); //flush CR, LF, or anything else.
          Serial.print(ch);
          Serial.println(". \nThis expects no bottles and a weight standard of 50g.");
          Serial.println("\nIf 50g calibration standard is in place, enter g or just enter to cancel.");
          while (Serial.available() == 0); 
          if (Serial.read() == 'g') {
              adcAmp[ch>>1]->setMUX(diffList[ch&1]); //Select Mux channel 0 or 1 for corresponding board 
              delay(200);
              //Apply offset correction before read
              adcAmp[ch>>1]->writeRegister(OFC0_REG, CALSys[ch>>1][ch&1].OFC0);
              adcAmp[ch>>1]->writeRegister(OFC1_REG, CALSys[ch>>1][ch&1].OFC1);
              adcAmp[ch>>1]->writeRegister(OFC2_REG, CALSys[ch>>1][ch&1].OFC2);
              CALSys[ch>>1][ch&1].FSC=50.0/(adcAmp[ch>>1]->convertToVoltage(adcAmp[ch>>1]->readSingle()) * 28571.429); //Error ratio to 50g
              EEPROM.put(CALSysSize*ch+3, CALSys[ch >> 1][ch & 1].FSC);
              Serial.print("Amp Gain Calibrated with factor: ");
              Serial.println(CALSys[ch >> 1][ch & 1].FSC,4);
              readFlush();
              break;
          }
          Serial.println("Gain Calibration Canceled!");
          readFlush();
          break;
      case 'i':  //change or report interval time in seconds
            delay(10);  //wait to receive second char in serial
            ch = readLine(cmd, sizeof(cmd)); //receive command  //terminate las in array position 6 if 5 chars came in 
            if (ch == 0) { //Just enter so report back
                Serial.print("Current interval in seconds is: ");
                Serial.println(interval);
            }
            else  //set interval
            {
                if (atol(cmd) < 10 || atol(cmd) >99999 || Serial.available()) {
                    Serial.println("Wrong interval, min is 10, max 99999, try again");
                    readFlush();
                    break;
                }
                interval=atol(cmd);
                Serial.print("Setting seconds interval to: ");
                Serial.println(interval);
                EEPROM.put(96, interval);
                break;
            }
            break;
      case 'o': //Perform a system offset calibration weight cells
          Serial.println("Starting offset Calibration. This expects you already have all bottles empty in place and undisturbed...");
          for (uint8_t brd = 4; brd--;) {   //Do Boards 3 to 0
              for (uint8_t brdCH = 2; brdCH--;) {  //Channel in each board 1 (dif 2+3) and 0 (dif 0+1)
                  adcAmp[brd]->setMUX(diffList[brdCH]);
                  delay(200);
                  adcAmp[brd]->sendDirectCommand(SYSOCAL);
                  adcAmp[brd]->waitForLowDRDY();
                  CALSys[brd][brdCH].OFC0 = adcAmp[brd]->readRegister(OFC0_REG);
                  CALSys[brd][brdCH].OFC1 = adcAmp[brd]->readRegister(OFC1_REG);
                  CALSys[brd][brdCH].OFC2 = adcAmp[brd]->readRegister(OFC2_REG);
                  EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH), CALSys[brd][brdCH].OFC0);
                  EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) +1, CALSys[brd][brdCH].OFC1);
                  EEPROM.update((CALSysSize * brd * 2) + (CALSysSize * brdCH) +2, CALSys[brd][brdCH].OFC2);
              }
          }
          Serial.println("Amps Offset Calibrated!");
        break;
      case 't':  //Touch calibration
        for (uint8_t i = 4; i--;) {
            i2cMux[i].setChannel(CHAN0); //Turn on this MUX , otherwise should be 0 (disconnected)
            QTouch[i].calibrate();
            i2cMux[i].setChannel(CHAN_NONE); //Turn off this MUX so doesn't short multiple I2C branches together
            delay(100);
        }
        Serial.println("Touch Calibrated!");
        break;
      // EVENT STREAM: licks emit onset/offset in real time; weights emit every INTERVAL.
      // Output is  timestamp_ms , id , amplitude   (id 0-7 weight g, 8-15 onset, 16-23 offset)
      case 'r':
        cTime = millis();
        streaming = true;
        for (uint8_t i = 0; i < 8; i++) touchState[i] = false;  //start from a clean slate
        Serial.println(F("# timestamp_ms,id,amplitude"));
        Serial.println(F("# id 0-7 weight g | 8-15 lick onset | 16-23 lick offset"));
        while (Serial.read() != 's') //The stream is stopped by an 's' received from the serial port
        {
          if (millis() - cTime > interval * 1000) { //INTERVAL sec past, so emit all weights
            cTime = millis(); //reset
            for (uint8_t brd = 0; brd < 4; brd++) {
                for (uint8_t brdCH = 0; brdCH < 2; brdCH++) {
                    adcAmp[brd]->setMUX(diffList[brdCH]); //Select channel in board
                    delayWTouch(100);  //Delay and keep sampling touch during settle
                    //recover right calibration offset parameters for the board/channel used
                    adcAmp[brd]->writeRegister(OFC0_REG, CALSys[brd][brdCH].OFC0);
                    adcAmp[brd]->writeRegister(OFC1_REG, CALSys[brd][brdCH].OFC1);
                    adcAmp[brd]->writeRegister(OFC2_REG, CALSys[brd][brdCH].OFC2);
                    //cell @5V should give around 3.5mV/100g(FS) or 35uV/g. 1/35uV= 28571.429
                    emitEvent((brd << 1) + brdCH,
                              adcAmp[brd]->convertToVoltage(adcAmp[brd]->readSingle()) * 28571.429 * CALSys[brd][brdCH].FSC);
                }
            }
          }
          updateTouch();  //Sample touch; emits onset/offset events as they happen
        }
        streaming = false;
        Serial.println("Data stop received!");
        break;
      case 'h': //Help
          helpSumary();
        break;
      case 'y':  //Hidden command to reset board 0 to 3
          delay(5);  //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          adcAmp[ch]->sendDirectCommand(0xFE);
          Serial.println("RST");
          valCfg(ch);
          break;
      //--------------------------------------------------------------------------------------------------------

      case 's':  //change sensitivity threshold in touch channel 0 to 7, so s1 will let you set threshold for ch 1.
          Serial.print("\nSetting lick sensitivity threshold for channel ");
          delay(5);  //wait to receive second char in serial
          ch = Serial.read() - '0';//receive and convert to integer
          if (ch < 0 || ch > 7 || Serial.available()>1) { //validate channel
              Serial.println("\nWrong channel!\nUse sX where X is channel 0 to 7, ex. s2 and enter.");
              readFlush();
              break;
          }
          readFlush(); //flush CR, LF, or anything else.
          i2cMux[ch >> 1].setChannel(CHAN0); //Activate I2C to current touch sensor
          Serial.print(ch); Serial.print(" .Current threshold is: "); Serial.println(QTouch[ch>>1].getNTHRForKey((ch&1)+1));
          Serial.println("Now enter value from 20 to 255, default was 130, or just enter to cancel");
          i2cMux[ch >> 1].setChannel(CHAN_NONE); //De-activate I2C to current touch sensor
          while (!Serial.available()) {}
          cmdLen = readLine(cmd, sizeof(cmd)); //receive command  //terminate las in array position 4 if 3 chars came in 
          if (cmdLen >0) { //Just enter so report back
              if (atoi(cmd) < 10 || atoi(cmd) > 255 || Serial.available()) {  //If out of range or more digits than 3
                  Serial.println("Wrong Threshold, min is 10, max 255, try again");
                  readFlush();
                  break;
              }
              touchTH[ch] = atoi(cmd); //Assign threshold for selected channel
              EEPROM.update(100+ch, touchTH[ch]);  //Save it in EEPROM
              i2cMux[ch >> 1].setChannel(CHAN0);//Activate I2C to current touch sensor
              QTouch[ch>>1].setNTHRForKey(touchTH[ch], (ch&1)+1);  //set the threshold for ch 1 or 2 in current touch board
              i2cMux[ch >> 1].setChannel(CHAN_NONE); //De-activate I2C to current touch sensor
              Serial.print("Set to: ");Serial.println(touchTH[ch]);
              break;
          }
          break;   

      case 'l':  //only licking test brd 0 to 3, both ports (DEBUG FUNCTION)
          delay(5);  //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          if (ch < 0 || ch >3) {
              Serial.println("Bad Command!");
              break;
          }
          while (Serial.read() != 's') //The conversion is stopped by a character received from the serial port
          {
              i2cMux[ch].setChannel(CHAN0);//Turn on access to this brd
              for (uint8_t brdCH = 2; brdCH--;) {
                  if (QTouch[ch].isTouch(BCHi[brdCH])) {  // if there was a touch at channel 1 or 2 in each chip (0 is for comp. guard)
                      //Run arrays values from 7 to 0 (odd)   
                      if (!doOnce[(ch << 1) + brdCH]) {
                          doOnce[(ch << 1) + brdCH] = true;
                          lickCnt[(ch << 1) + brdCH]++;
                          T[(ch << 1) + brdCH] = millis(); //Start Lick
                      }
                  }
                  else if (doOnce[(ch << 1) + brdCH]) { //this touch is released 
                      doOnce[(ch << 1) + brdCH] = false;
                      T[(ch << 1) + brdCH] = millis() - T[(ch << 1) + brdCH]; //capture end of lick timing
                      lickAvg[(ch << 1) + brdCH] += T[(ch << 1) + brdCH]; //accumulate lick time length 
                  }
              }
              i2cMux[ch].setChannel(CHAN_NONE);//Turn off access to this chip
              Serial.print("LickCnt0: ");
              Serial.print(lickCnt[ch << 1]); 
              Serial.print("  Times 0: ");
              Serial.print(T[ch << 1]);
              Serial.print("\t\t     LickCnt1: ");
              Serial.print(lickCnt[(ch << 1) + 1]);
              Serial.print("  Times 1: ");
              Serial.println(T[(ch << 1) + 1]);
              delay(50);
          }
          break;
      case 'g': //Weight Basic registers testing (DEBUG FUNCTION)
          delay(5);  //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          Serial.print("CH: ");
          Serial.println(ch);
          Serial.print("PGA: ");
          Serial.println(adcAmp[ch]->readRegister(ADCON_REG) & 0x07);
          Serial.print("MUX: 0x");
          Serial.println(adcAmp[ch]->readRegister(MUX_REG), HEX);
          Serial.print("DRATE: ");
          Serial.println(adcAmp[ch]->readRegister(DRATE_REG));
          break;
      case 'm': //Weight Mux testing (DEBUG FUNCTION)
          delay(5); //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          adcAmp[ch]->setMUX(DIFF_0_1);
          delay(100);
          Serial.print("MUX: 0x");
          Serial.println(adcAmp[ch]->readRegister(MUX_REG), HEX);
          break;
      case 'v':  // Check if configuration still OK for 0 to 3, otherwise report and recover (DEBUG FUNCTION)
          delay(5); //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          valCfg(ch);
          Serial.println("OK!");
          break;
      case 'x':  //Read just one board both dif channels 0+1 and 2+3 (DEBUG FUNCTION)
          delay(5); //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          for (uint8_t brdCH = 2; brdCH--;) {  //Channel in each board 1 (dif 2+3) and 0 (dif 0+1)
              adcAmp[ch]->setMUX(diffList[brdCH]); //Select channel in board
              delay(200);
              //recover right calibration offset parameters for the board/channel used
              adcAmp[ch]->writeRegister(OFC0_REG, CALSys[ch][brdCH].OFC0);
              adcAmp[ch]->writeRegister(OFC1_REG, CALSys[ch][brdCH].OFC1);
              adcAmp[ch]->writeRegister(OFC2_REG, CALSys[ch][brdCH].OFC2);
              //cell @5V should give around 3.5mV/100g(FS) or 35uV/g. 1/35uV= 28571.429
              //Internally ADC Gain PGA is 64 so the converter sees 192mV/100g(FS) or 2.24mV/g 
              Serial.print(adcAmp[ch]->convertToVoltage(adcAmp[ch]->readSingle()) * 28571.429 * CALSys[ch][brdCH].FSC, 1);
              Serial.print("g  ");

          }
          Serial.println("");
          break;
      case 'z': //See actual weight calibration in use (DEBUG FUNCTION)
          delay(5); //wait to receive second char in serial
          ch = Serial.read() - '0'; //receive and convert
          Serial.print(CALSys[ch][0].OFC2, HEX); Serial.print(" ");
          Serial.print(CALSys[ch][0].OFC1, HEX); Serial.print(" ");
          Serial.print(CALSys[ch][0].OFC0, HEX); Serial.print(" ");
          Serial.print(CALSys[ch][0].FSC, 4); Serial.print("   ");
          Serial.print(CALSys[ch][1].OFC2, HEX); Serial.print(" ");
          Serial.print(CALSys[ch][1].OFC1, HEX); Serial.print(" ");
          Serial.print(CALSys[ch][1].OFC0, HEX); Serial.print(" ");
          Serial.println(CALSys[ch][1].FSC, 4);
          break;
      case '\r': // CR ignore
      case '\n': // LF ignore
          break;
          //--------------------------------------------------------------------------------------------------------
      default:
          Serial.print("Wrong Command: ");
          Serial.println(commandCharacter);
    }
    readFlush(); //Clear garbage in buffer
    prompt = false;
  }
}

void valCfg(uint8_t brd) {
    if ((adcAmp[brd]->readRegister(ADCON_REG) & 0x07) == 0 || adcAmp[brd]->readRegister(DRATE_REG) == DRATE_30000SPS){
        Serial.println("Reset detected, recovering configuration...");
        adcAmp[brd]->setPGA(PGA_64); 
        adcAmp[brd]->setDRATE(DRATE_5SPS);
    }
}

// Single event line:  timestamp_ms , id , amplitude
void emitEvent(uint8_t id, float amp) {
    Serial.print(millis());
    Serial.print(',');
    Serial.print(id);
    Serial.print(',');
    Serial.println(amp, 1);
}

//Call back function to support I2C touch during delays
void delayWTouch(int16_t del) {  //delay in chunks of 20mS , ex. delayWTouch(100) will delay 20mS X 5 times and a bit more
    for (; del>0; del-=20) {
        updateTouch();
        delay(20);
    }
}

// Sample all 8 touch keys; on each state change, emit an onset (id 8-15) or
// offset (id 16-23) event. No counts/averages are computed.
void updateTouch() {
    for (char brd = 4; brd--;) {
        i2cMux[brd].setChannel(CHAN0);                       //Turn on access to this board
        for (uint8_t brdCH = 2; brdCH--;) {
            uint8_t ch = (brd << 1) + brdCH;                 //station 0..7
            bool nowTouch = QTouch[brd].isTouch(BCHi[brdCH]);//key 1 or 2 (0 is comp. guard)
            if (nowTouch && !touchState[ch]) {               //rising edge -> ONSET
                touchState[ch] = true;
                digitalWrite(LED, 1);
                if (streaming) emitEvent(8 + ch, 1);
            }
            else if (!nowTouch && touchState[ch]) {          //falling edge -> OFFSET
                touchState[ch] = false;
                digitalWrite(LED, 0);
                if (streaming) emitEvent(16 + ch, 0);
            }
        }
        i2cMux[brd].setChannel(CHAN_NONE);                   //Turn off access to this chip
    }
}
