

from flask import Flask, redirect, request, abort, render_template
from evdev import InputDevice
from select import select
import RPi.GPIO as GPIO
import threading
import sqlite3
import signal
import struct
import ctypes
import string
import time
import json
import os

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
autodoorRunning = True

def scannerLoop(scanner):
    dev = InputDevice(scanner)
    msg = ""
    while True:
        r,w,x = select([dev], [], [])
        for event in dev.read():
            if event.type==1 and event.value==1 and autodoorRunning:
                if event.code != 28:
                    msg += keys[event.code]
                else:
                    valid, reason = validate(msg)
                    if valid:
                        openDoor(msg)
                    else:
                        log(reason)
                    msg = ""


def mouseLoop():
    #Check for mouse
    mouse = open("/dev/input/mice", "r+b", 0)
    data = ""
    #lock.acquire()
    print(f"Thread {threading.current_thread().name}({threading.get_native_id()}) acquired lock") #get_native_id is the id the kernel gives to the thread, may be reused
    while True:
        data = mouse.read(3)  # Reads the 3 bytes
        unpacked = struct.unpack('3b',data)  #Unpacks the bytes to integers
        if unpacked == (9,0,0) and autodoorRunning: # check left click
            openDoor("mouse")
    #print("Out of while loop")
    #lock.release()
    #return

def validate(msgToValidate: str) -> list:
    timeOfAttempt = time.localtime()
    timeHour = timeOfAttempt.tm_hour
    timeMinute = timeOfAttempt.tm_min
    dayOfAttempt = timeOfAttempt.tm_wday
    outOfTimeMsg = f"Out of time scan by [{msgToValidate}]"
    outOfTimeWeekendMsg = f"Out of time scan (weekend) by [{msgToValidate}]"
    invalidStudentMsg = f"User [{msgToValidate}] Invalid"
    validStudentMsg = f"User [{msgToValidate}] Valid"

    if msgToValidate in students:
        #Checks if it's a weekday and returns false if it's a weekend
        #if not dayOfAttempt in schoolDays:
        #    return [False, outOfTimeWeekendMsg]

        # checks hour
        if schoolStartHour <= timeHour <= schoolEndHour:
            #checks if time = start time
            if timeHour == schoolStartHour:
                # checks if min > start min
                if schoolStartMinute <= timeMinute:
                    return [True, validStudentMsg]
                return [False, outOfTimeMsg]
            #check if time = end time
            if timeHour == schoolEndHour:
                # checks if min > start min
                if schoolEndMinute > timeMinute:
                    return [True, validStudentMsg]
                return [False, outOfTimeMsg]
            # checks if its lunch hour
            if lunchStartHour <= timeHour <= lunchEndHour:
                # check if min is within lunch
                if lunchStartMinute <= timeMinute < lunchEndMinute:
                    return [False, outOfTimeMsg]
            return [True, validStudentMsg]
        else:
            return [False, outOfTimeMsg]


        #return True
    return [False, invalidStudentMsg]

def openDoor(whosOpeningDoor: str):
    if whosOpeningDoor == "mouse":
        log("Mouse opening door")
    else:
        log(f"{whosOpeningDoor} opening door")
    #GPIO.setmode(GPIO.BCM)
    try:
        GPIO.output(LEDPin, GPIO.HIGH) #led on
        SERVO.ChangeDutyCycle(4) # servo on
        time.sleep(2)
        GPIO.output(LEDPin, GPIO.LOW) #led off
        SERVO.ChangeDutyCycle(2) # servo closing
        time.sleep(0.1)
        SERVO.ChangeDutyCycle(0) # servo full close
    except Exception as e:
        log(f"Exception occured: {e}")
        GPIO.output(LEDPin, GPIO.LOW)

#def log(logStatement: str):
#    logStatement = f"{time.asctime()}: " + logStatement
#    print(logStatement)
#    with open("/home/pi/AutoDoor2.log", "a") as logFile:
#        logFile.write(logStatement+"\n")

def log(logStatement: str, toPrint=True):
    timeOfLog = round(time.time())
    timeReadable = time.asctime(time.localtime(timeOfLog))
    db = sqlite3.connect("db.Autodoor.sqlite")
    cursor = db.cursor()
    cursor.execute(f"INSERT INTO logs VALUES ({timeOfLog}, '{timeReadable}', '{logStatement}')")
    db.commit()
    cursor.close()
    db.close()
    if toPrint:
        print(f"{timeReadable}: {logStatement}")


def scanForScanners() -> int:
    #Function to check for scanners
    availableInputDevices = os.popen("ls /dev/input/by-id/").read().strip().split("\n")
    indexNumber = 1
    userSelectedScanner = ""
    scannerIndexMappings = {}

    #While loop to facilitate user selecting a scanner to use
    while not userSelectedScanner.isnumeric():
        for inputDevice in availableInputDevices:
            print(f"{indexNumber}: {inputDevice}")
            scannerIndexMappings[indexNumber] = inputDevice
            indexNumber += 1

        #If there are multiple scanners available, ask for input on which scanner to select
        if len(availableInputDevices) != 1:
            log("Available scanners - " + str(scannerIndexMappings).replace('\'', ''), toPrint=False) #f-strings can't have backslashes so no f-string here, replacing single quotes to not generate SQl errors
            userSelectedScanner = input(f"Select your scanner (1-9): ")
            
            log(f"User selected scanner {scannerIndexMappings[int(userSelectedScanner)]}")
        #Otherwise automatically select the only scanner available
        else:
            log(f"Only one scanner available, defaulting to {inputDevice}")
            userSelectedScanner = "1"

    #scanner = "/dev/input/by-id/" + availableInputDevices[int(userSelectedScanner)-1]
    scanner = "/dev/input/by-id/" + scannerIndexMappings[int(userSelectedScanner)]

    return scanner

def initialize() -> list:
    #Reads config file config.json
    with open("config.json", "r") as configFileHandler:
        configRaw = configFileHandler.read()
    #Loads file into JSON
    config = json.loads(configRaw)
    #Defines values from config.json
    LEDPin = config["LEDPin"]
    ServoPin = config["ServoPin"]
    logFileLoc = config["logFile"]
    schoolStartHour = config["starth"]
    schoolEndHour = config["endh"]
    schoolStartMinute = config["startmin"]
    schoolEndMinute = config["endmin"]
    lunchStartHour = config["lstarth"]
    lunchEndHour = config["lendh"]
    lunchStartMinute = config["lstartmin"]
    lunchEndMinute = config["lendmin"]
    students = config["list"]
    
    #Cleanse student list by removing non-printable characters
    students = list(filter(lambda x: x in string.printable, students))
    #As this will return a list with each separate character, everything needs to be concateneted together, will also strip out charage returns for linux windows new line compatability
    #Starting and ending new lines are also stipped here, along with splitting of \n to provide a just list of student numbers
    students = "".join(students).replace("\r", "").strip().split(",")

    #Creates a list of values to be used later in the program like student numbers and the admin key
    initalizedValues = [students, LEDPin, ServoPin, logFileLoc, schoolStartHour, schoolEndHour, schoolStartMinute, schoolEndMinute, lunchStartHour, lunchEndHour, lunchStartMinute, lunchEndMinute, scanForScanners()]
    log("Values initialized")


    
    return initalizedValues

@app.get("/")
def index():
    return render_template("index.html", logs=getLogs())

@app.get("/start")
def start():
    global autodoorRunning
    autodoorRunning = True

    return "Autodoor Started"

@app.get("/stop")
def stop():
    global autodoorRunning #Must be declared global here otherwise it's not accessible inside the function
    autodoorRunning = False

    return "Autodoor Stopped"

@app.get("/config")
def getConfig():
    with open('config.json',"r") as f:
        configStr = f.read()
        return configStr, 200
    
@app.get("/logs/all")
def getLogs():
    db = sqlite3.connect("db.Autodoor.sqlite")
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM logs;")
    logsList = cursor.fetchall()
    logs = ""
    for logItem in logsList:
        logs += f"{logItem[1]} - {logItem[2]}\n"
    db.commit()
    cursor.close()
    db.close()
    return logs.strip()
    
@app.get("/logs/latest/<lastLogCheck>")
def getLatestLogs(lastLogCheck):
    db = sqlite3.connect("db.Autodoor.sqlite")
    cursor = db.cursor()
    cursor.execute(f"SELECT * FROM logs WHERE Time BETWEEN {lastLogCheck} and {time.time()};")
    logsList = cursor.fetchall()
    logs = ""
    for logItem in logsList:
        logs += f"{logItem[1]} - {logItem[2]}\n"
    db.commit()
    cursor.close()
    db.close()
    print(logs)
    return logs.strip()
    
@app.get("/checkin")
def checkIn():
    return "Connected"


keys = "X^1234567890XXXXqwertzuiopXXXXasdfghjklXXXXXyxcvbnmXXXXXXXXXXXXXXXXXXXXXXX"
students, LEDPin, ServoPin, logFileLoc, schoolStartHour, schoolEndHour, schoolStartMinute, schoolEndMinute, lunchStartHour, lunchEndHour, lunchStartMinute, lunchEndMinute, scanner = initialize()
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False) #Disable the "This channel is already in use, continuing anyway." warning
GPIO.setup(ServoPin, GPIO.OUT) #SERVO
GPIO.setup(LEDPin, GPIO.OUT, initial=GPIO.LOW) #LED
#GPIO.output(LEDPin, GPIO.LOW)
SERVO = GPIO.PWM(ServoPin, 50)
SERVO.start(0)
allProcesses = []
schoolDays = [0,1,2,3,4] #Weekdays 0=mon, 1=tue, 2=wed, 3=thu 4=fri
lock = threading.RLock()
lastLogTime = time.time()
log("Set variables")
try:
    mouseThread = threading.Thread(target=mouseLoop)
    mouseThread.name = "MouseThread"
    #mouseThread = thread_with_exception("Mouse")
    scannerThread = threading.Thread(target=scannerLoop, args=(scanner,))
    scannerThread.name = "ScannerThread"
    #wsThread = threading.Thread(target=asyncio.run, args=(WebSocketServer().main()))

    mouseThread.start()
    scannerThread.start()
    #mouseThread.raise_exception()
    #mouseThread.join()

    print("\nAutodoor V3 starting, press Ctrl+C to exit")
    app.run(host="0.0.0.0", debug=False)
    #flaskThread = threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "debug": False})
    print("\nPress Ctrl+C again to exit")


    #mouseThread.join()
    #scannerThread.join()
    #flaskThread.join()
except KeyboardInterrupt:
    log("Running GPIO cleanup")
    GPIO.cleanup()
    exit()

#websocketServer = WebSocketServer()
