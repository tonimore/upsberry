#!/usr/bin/env python
# -*- coding: utf-8 -*-
# You need install:
# sudo pip install --upgrade RPi.GPIO

# To get PowerON status you need make changes as described:
# https://github.com/linshuqin329/UPS-18650/issues/4

# for localization emails see ups.conf


from __future__ import print_function
import os
import sys
import logging
import struct
import smbus
import sys
import time
import datetime
import signal
import smtplib
import RPi.GPIO as GPIO
import ctypes
import Queue
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email import Charset

# for debug only. Can be removed
if len(sys.argv) > 1 and sys.argv[1] == "remotedebug":
    import ptvsd
    ptvsd.enable_attach(address=('0.0.0.0', 5678), redirect_output=True)
    ptvsd.wait_for_attach()
    breakpoint()

# =================================================================================================
# This values can be overrided in the ups.conf
version = "1.0"
program_name = "UPS1865 Service"
log_file = ""

# I2C Bus and address:
smbus_id = 1
smbus_addr = 0x36
# Minimal Voltage changing in % to write to log
log_voltage_percent = 0.3
# Minimal Capacity changing in % to write to log
log_capacity_percent = 2

# Capacity values to generate events:
battery_critical_level = 10
battery_low_level = 20
battery_high_level = 80

# measurements count for calculating average values for email notification
data_count = 10

# Call shutdown command at battery Critical event
auto_shutdown = True

# email notification settings. See ups.conf.
# enable/disable email sending
send_email = False
# end of configuration 
# =================================================================================================


def m(message):
    try:
        return messages[message]
    except:
        return message    

running = True

# Global objects:
bus = None
logger = None
data = Queue.LifoQueue(data_count)


# User defined event functions:
def onPowerLost():
    pass

def onPowerRestore():
    pass

def onBatteryHigh():
    pass

def onBatteryMedium():
    pass

def onBatteryLow():
    pass

def onBatteryCritical():
    pass


def before_exit():
    global running
    running = False

def exit_gracefully(signum, frame):
    # restore the original signal handler as otherwise evil things will happen
    # in raw_input when CTRL+C is pressed, and our signal handler is not re-entrant
    signal.signal(signal.SIGINT, original_sigint)
    print ("Exiting by Ctrl-C...\n", file=sys.stderr)
    before_exit()

def exit_gracefully2(signum, frame):
    signal.signal(signal.SIGTERM, original_sigterm)
    print ("Exiting by TERM...\n", file=sys.stderr)
    before_exit()
original_sigint = signal.signal(signal.SIGINT,  exit_gracefully)
original_sigterm = signal.signal(signal.SIGTERM, exit_gracefully2)

class evnt:
    powerLost = 1
    powerRestore = 2
    batteryHigh = 3
    batteryMedium = 4
    batteryLow = 5
    batteryCritical = 6
    batteryUnk = 9
    shutdown = 10

events = {
    evnt.powerLost : ["Power Lost", onPowerLost],\
    evnt.powerRestore : ["Power Restore", onPowerRestore],\
    evnt.batteryHigh : ["Battery High", onBatteryHigh],\
    evnt.batteryMedium : ["Battery Medium", onBatteryMedium],\
    evnt.batteryLow : ["Battery Low", onBatteryLow],\
    evnt.batteryCritical : ["Battery Critical", onBatteryCritical],\
    evnt.batteryUnk : ["Battery Unknown", None],\
    evnt.shutdown : ["Shutdown Initiated", None],\
}

def shutdown():
    logger.warning("+++ System shutdown initiated.")
    send_email(evnt.shutdown)

    time.sleep(10)
    os.system("shutdown")

def send_email(ev):
    if not send_email: return

    c = 0
    v = 0
    num = float(data.qsize())
    while not data.empty():
        i = data.get()
        c = c + i["Current"]
        v = v + i["Voltage"]
    if num > 0:
        c = float(c) / num
        v = float(v) / num    

    # Message body
    # do not need use form: u"text"  why?
    text = "{msg1}: {event}\r\n{msg2}: {ts}\r\n{msg3}:\r\n\t{volt_t}: {volt:.2f}\r\n\t{curr_t}: {curr}".format(\
        event=m(events[ev][0]),\
        msg1=m("State changed to"),\
        msg2=m("Event occured at"),\
        msg3=m("Last measured data"),\
        ts=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),\
        volt_t=m("Voltage"), volt=v,\
        curr_t=m("Current"), curr=c)

    # Default encoding mode set to Quoted Printable. Acts globally!
    Charset.add_charset('utf-8', Charset.QP, Charset.QP, 'utf-8')


    # For Multipart message:
    # 'alternative’ MIME type – HTML and plain text bundled in one e-mail message
    #msg = MIMEMultipart('alternative') 
    # Attach both parts
    #htmlpart = MIMEText(html, 'html', 'UTF-8')
    #textpart = MIMEText(text, 'plain', 'UTF-8')
    #msg.attach(htmlpart)
    #msg.attach(textpart)
    
    # For Plain text only message:
    msg = MIMEText(text, 'plain', 'UTF-8')


    msg['Subject'] = str(Header("{}: [{}]".format(subject, m(events[ev][0])) , 'utf-8'))

    # Only descriptive part of recipient and sender shall be encoded, not the email address
    msg['From'] = "\"{}\" <{}>".format(Header(mail_from[0], 'utf-8'), mail_from[1])
    #msg['To']   = "\"{}\" <{}>".format(Header(mail_to[0],   'utf-8'), mail_to[1])

    # prepare fileds To: for multiple recipients
    to_msg = ""
    to_rcp = []
    for l in mail_to:    
        to_msg = to_msg + "\"{}\" <{}>, ".format(Header(l[0], 'utf-8'), l[1]) # for header: name in unicode, address as is
        to_rcp.append(l[1]) # for send_email: array of addresses only
      
    msg['To'] =  to_msg

    try:        
        server = smtplib.SMTP(smtp_server)
        #server.set_debuglevel(1)
        server.sendmail("", to_rcp, msg.as_string())
        server.quit()
    except Exception as e:
        logger.error("Exception during send email: {}".format(e))    
        

def read_voltage():
    "This function returns as float the voltage from the Raspi UPS Hat via the provided SMBus object"
    try:
        read = bus.read_word_data(smbus_addr, 2)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        voltage = swapped * 1.25 /1000/16
        return voltage
    except Exception as e:
        logger.error("Read Voltage SMbus failed: {}".format(e))
        return 0.001

def read_capacity():
    "This function returns as a float the remaining capacity of the battery connected to the Raspi UPS Hat via the provided SMBus object"
    try:
        read = bus.read_word_data(smbus_addr, 4)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        capacity = swapped/256
        if capacity == 0:
            return 0.001
        return capacity
    except Exception as e:
        logger.error("Read Capacity SMbus failed: {}".format(e))
        return 0.001

def read_current():
    "This function returns as a integer charge current. Used undocumented register 20."
    try:
        read = bus.read_word_data(smbus_addr, 20)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        #current = ctypes.c_int16(swapped)
        if swapped < 32768: current = swapped
        else: current = swapped - 65536
        return current
    except Exception as e:
        logger.error("Read Current SMbus failed: {}".format(e))
        return 0

def powerOK():
    try:
        return bool(GPIO.input(4))
    except Exception as e:
        logger.error("Read GPIO4 (PowerON) failed: {}".format(e))
        return True

def notify(ev):
    logger.warn('State changed to: {}'.format(events[ev][0]))
    try: 
        if events[ev][1]: events[ev][1]()
    except Exception as e:
        logger.error('User onEvent [{}] function call failed: {}'.format(events[ev][0],e))

    send_email(ev)                
    
def main_loop():
    global bus, running
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(4, GPIO.IN)
    except Exception as e:
        logger.error("Cannot initalize GPIO: {}".format(e))    
        exit(1)

    try:
        bus = smbus.SMBus(smbus_id) 
    except Exception as e:
        logger.error("Cannot connect to SMBus {}: {}".format(smbus_id, e))    
        exit(1)

    # check that SMBus readig possible:    
    try:
        read = bus.read_word_data(smbus_addr, 0)
    except Exception as e:
        logger.error("Cannot read SMBus: {}".format(e))    
        exit(1)


    onBattery = False 

    last_voltage = 0.01
    last_battery = evnt.batteryUnk
    last_capacity = 100

    # MAIN LOOP
    while running:
        
        if not powerOK():
            if not onBattery:
                onBattery = True
                notify(evnt.powerLost)
        else:
           if onBattery:
                onBattery = False
                notify(evnt.powerRestore)

        now_capacity = read_capacity()
        now_voltage = read_voltage()
        now_current = read_current()

        if data.full(): data.get()
        data.put({"Current" : now_current, "Voltage" : now_voltage, "ts" : time.time()})

        logger.debug("PowerON {}; Voltage {:.2f}; Capacity {}; Current: {}".format(powerOK(), now_voltage, now_capacity, now_current))

        if now_capacity < battery_critical_level:
            if last_battery != evnt.batteryCritical:
                last_battery = evnt.batteryCritical
                notify(evnt.batteryCritical)
        elif now_capacity <= battery_low_level:
            if last_battery != evnt.batteryLow:
                last_battery = evnt.batteryLow
                notify(evnt.batteryLow)
        elif now_capacity <= battery_high_level:
            if last_battery != evnt.batteryMedium:
                last_battery = evnt.batteryMedium
                notify(evnt.batteryMedium)
        else:
            if last_battery != evnt.batteryHigh:
                last_battery = evnt.batteryHigh
                notify(evnt.batteryHigh)

        # add to log value only if it changed more then log_xxxxx_percent
        if abs(float(now_capacity-last_capacity) / (float(last_capacity) / 100)) > log_capacity_percent:
            logger.info("Capacity changed: {}%".format(now_capacity))
            last_capacity = now_capacity

        if abs(float(now_voltage-last_voltage) / (float(last_voltage) / 100)) > log_voltage_percent:
            logger.info("Voltage changed: {:.2f}V".format(now_voltage))
            last_voltage = now_voltage

        if now_capacity < battery_critical_level and auto_shutdown and onBattery:
            running = False
            shutdown()

        time.sleep(10)

def main(arguments):
    global log_file
    global logger
    print('--- {}, version: {}'.format(program_name, version))

    # loading overrides values from file xxxxxx.conf
    
    # congiguration file can be beside main script or in the /etc directory. Uncomment line tou need:
    #config_file = os.path.splitext(os.path.realpath(sys.argv[0]))[0] + ".conf"
    config_file = "/etc/" + os.path.splitext( os.path.basename(sys.argv[0]) )[0] + ".conf"

    # if logfile not specified use xxxxxx.log
    if log_file == "":
        # log file can be beside main script or in the /var/log directory. Uncomment line tou need:
        #log_file = os.path.splitext(os.path.realpath(sys.argv[0]))[0] + ".log"
        log_file = "/var/log/" + os.path.splitext( os.path.basename(sys.argv[0]) )[0] + ".log"
        
    if os.path.exists(config_file):
        try:
            execfile(config_file, globals())
            print("Loaded config file: " + config_file)
        except:
            print("Error loading config file: {}".format(config_file), file=sys.stderr)
    else:
        print("Config file not found: " + config_file, file=sys.stderr)

    if log_file == "":
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s', filename=log_file)
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')

    logger = logging.getLogger(__name__)
    logger.info('--- {}, version: {}'.format(program_name, version))

    main_loop()
    logger.info('--- {} finished.'.format(program_name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

