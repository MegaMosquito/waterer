#
# This is the code for my plant waterer, with:
#   24V power supply, with 5V buck convertor for Pi, and accessories
#   0.96" i2c monochrom OLED display with yellow and blue filter cover
#   moisture sensor attached to spi MCP3008 ADC chip
#   resistor/transistor/relay to turn on/off the 24V water control valve
#   pushbutton enabling user to manually initiate a watering event (active high)
#   web UI for finer control
#
# Written by mosquito@darlingevil.com, 2021-7-31
#


import os
import json
import time
from datetime import datetime, timedelta
import busio
import board
import digitalio
import subprocess
import threading
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn
import RPi.GPIO as GPIO
from flask import Flask, request


# *** Debug ***

DEBUG_CONFIG = False
DEBUG_LOG = False
DEBUG_REST = True
DEBUG_BUTTON = False
DEBUG_NEXT = False
DEBUG_SENSOR = False
DEBUG_NEXT_WHEN = False
DEBUG_WATERING = False

# Debug print
def debug(flag, str):
  if flag:
    print(str)


# ***** Flask *****

# For development of the web UI, you can disable the REST API to only log
DISABLE_REST_ACTIONS = True

# Flask server details
BIND_ADDRESS = '0.0.0.0'
BIND_PORT = 8080
webapp = Flask('waterer')

def server_thread():
  webapp.run(host=BIND_ADDRESS, port=BIND_PORT)

# Must start the web server in a thread since it blocks
webapp_thread = threading.Thread(target=server_thread, args=())
webapp_thread.start()


# ***** Config *****

# Main loop sleep time in seconds (minimize for responsiveness, but eats CPU)
SLEEP_SEC = 0.75

# How long the button must be helf to indicate a long press (start watering)
LONG_PRESS_SEC = 3

# Get the IP address from the environment (it must be passed by `docker run`)
LOCAL_IP_ADDRESS      = os.environ['LOCAL_IP_ADDRESS']

# Where is the config file located?
CONFIG_FILE = '/config.json'

# Where is the log file located?
LOG_FILE = '/log.json'

# Load the configuration from disk
def load_config():
  global config
  f = open(CONFIG_FILE, 'r')
  config = json.load(f)
  f.close()
  debug(DEBUG_CONFIG, "LOADED:")
  debug(DEBUG_CONFIG, config)

# Save the configuration to disk
def save_config():
  debug(DEBUG_CONFIG, "SAVING:")
  debug(DEBUG_CONFIG, config)
  j = json.dumps(config, indent=2)
  f = open(CONFIG_FILE, 'w+')
  f.write(j)
  f.close()

# Update the config from the web UI
def update_config(sensor, dry, cooldown_min, timer, when, duration_sec, days):
  global config
  config_str = '{'
  config_str += '"sensor":' + sensor + ',' 
  config_str += '"dry":' + str(dry) + ','
  config_str += '"cooldown_min":' + str(cooldown_min) + ','
  config_str += '"timer":' + timer + ',' 
  config_str += '"when":"' + str(when) + '",'
  config_str += '"duration_sec":' + str(duration_sec) + ','
  config_str += '"days":"' + str(days) + '"'
  config_str += '}'
  config = json.loads(config_str)
  save_config()
  debug(DEBUG_CONFIG, "UPDATED:")
  debug(DEBUG_CONFIG, config)

# Initialize the global config dictionary from the config file
load_config()


# ***** Logfile *****

def log(s):
  debug(DEBUG_LOG, 'Writing: "' + s + '"')
  f = open(LOG_FILE, 'a+')
  f.write(s + '\n')
  f.close()

def log_reset():
  debug(DEBUG_LOG, 'Resetting log file.')
  f = open(LOG_FILE, 'w')
  f.close()
  log('{"reset":"' + datetime.now().strftime('%d/%m/%Y %I:%M%p') + '"}')

def log2json():
  f = open(LOG_FILE, 'r')
  l = f.readlines()
  f.close()
  logs = ','.join(l)
  j = '{"logs":[' + logs + ']}'
  return j


# ***** GPIO *****

PIN_PUSHBUTTON = 23
PIN_RELAY = 18

# Useful for debugging?
GPIO.setwarnings(False)

# Use this or GPIO.BOARD
GPIO.setmode(GPIO.BCM)

# Configure pushbutton input and relay output
GPIO.setup(PIN_PUSHBUTTON, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(PIN_RELAY, GPIO.OUT)
GPIO.output(PIN_RELAY, GPIO.LOW)

# Control the water valve relay
def water(tf, reason):
  if tf:
    GPIO.output(PIN_RELAY, GPIO.HIGH)
    debug(DEBUG_WATERING, "Water relay is ON!")
    log('{"watering":"' + datetime.now().strftime('%d/%m/%Y %I:%M%p') + '","reason":"' + reason + '"}')
  else:
    GPIO.output(PIN_RELAY, GPIO.LOW)
    debug(DEBUG_WATERING, "Water relay is OFF!")
    log('{"stopping":"' + datetime.now().strftime('%d/%m/%Y %I:%M%p') + '","reason":"' + reason + '"}')


# ***** SPI (for MCP3008) *****

# Configure SPI (NOTE: must first enable SPI on the host using `raspi-config`)
spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)

# Select the chip select pin
cs = digitalio.DigitalInOut(board.CE0)

# Create the MCP3008 object
MCP3008 = MCP.MCP3008(spi, cs)

# Create an analog input channel on pin 0 for the moisture sensor
moisture = AnalogIn(MCP3008, MCP.P0)

# Use these to get readings:
#   moisture.value (0 .. 65535)
#   moisture.voltage (0 .. 3.3V)


# ***** I2C (for OLED screen) *****

# Configure I2C (NOTE: must first enable I2C on the host using `raspi-config`)
i2c = board.I2C()

# Create the OLED display object (set WIDTH, HEIGHT for your display)
WIDTH = 128
HEIGHT = 64
OLED_RESET = digitalio.DigitalInOut(board.D4) # (not used)
oled = adafruit_ssd1306.SSD1306_I2C(WIDTH, HEIGHT, i2c, addr=0x3c, reset=OLED_RESET)

# Load the default font for the display.
font = ImageFont.load_default()

# Initialize the display
oled.fill(0)
oled.show()

# Create blank 1-bit color "image" for drawing on the monochrome OLED.
image = Image.new('1', (oled.width, oled.height))

# Get a draw object to use for drawing onto that "image".
draw = ImageDraw.Draw(image)

# Draw one line of text at the specified coordinates (column=x, row=y)
def text_xy(x, y, text):
  draw.text((x, y), text, font=font, fill=255)

# Draw one line of center-aligned text on row y
def text_centered_y(y, text):
  (font_width, font_height) = font.getsize(text)
  draw.text((oled.width//2 - font_width//2, y), text, font=font, fill=255)


# ***** web UI *****

@webapp.route('/status', methods=['GET'])
def rest_status():
  json_data = '{'
  json_data += '"startup":"' + startup + '",'
  json_data += '"sensor":"' + str(config['sensor']) + '",'
  if config['sensor']:
    json_data += '"next":"' + get_next_sensor_str() + '",'
  json_data += '"timer":"' + str(config['timer']) + '",'
  if config['timer']:
    json_data += '"next":"' + get_next_timer_str(datetime.now()) + '",'
  json_data += '"status":"running"'
  json_data += '}'
  print(json_data + '\n')
  return (json_data + '\n', 200)

@webapp.route('/config', methods=['GET', 'POST'])
def rest_config():
  if request.method == 'GET':
    json_data = json.dumps(config)
    return (json_data + '\n', 200)
  else: # method == POST
    sensor = request.form['sensor']
    dry = request.form['dry']
    cooldown_min = request.form['cooldown_min']
    timer = request.form['timer']
    when = request.form['when']
    duration_sec = request.form['duration_sec']
    days = request.form['days']
    debug(DEBUG_REST, 'REST: "/config" POST')
    debug(DEBUG_REST, '  dry="' + dry + '"')
    debug(DEBUG_REST, '  cooldown_min="' + cooldown_min + '"')
    debug(DEBUG_REST, '  timer="' + timer + '"')
    debug(DEBUG_REST, '  when="' + when + '"')
    debug(DEBUG_REST, '  duration_sec="' + duration_sec + '"')
    debug(DEBUG_REST, '  days="' + days + '"')
    if not DISABLE_REST_ACTIONS:
      update_config(sensor, dry, cooldown_min, timer, when, duration_sec, days)
    json_data = json.dumps(config)
    return (json_data + '\n', 200)

@webapp.route('/water', methods=['POST'])
def rest_water():
  action = request.form['action']
  debug(DEBUG_REST, 'REST: "/water" POST action=' + action)
  if 'water' == action:
    if not DISABLE_REST_ACTIONS:
      start_watering('webui')
    json_data = '{"action":"water"}'
    return (json_data + '\n', 200)
  elif 'stop' == action:
    if not DISABLE_REST_ACTIONS:
      end_watering('webui')
    json_data = '{"action":"stop"}'
    return (json_data + '\n', 200)
  json_data = '{"action":"ERROR! (action=' + action + ')"}'
  return (json_data + '\n', 400)

@webapp.route('/logs', methods=['GET', 'DELETE'])
def rest_logs():
  if request.method == 'GET':
    json_data = log2json()
    return (json_data + '\n', 200)
  else: # method == DELETE
    debug(DEBUG_REST, 'REST: "/logs" DELETE')
    if not DISABLE_REST_ACTIONS:
      log_reset()
    json_data = log2json()
    return (json_data + '\n', 200)

# Prevent caching everywhere
@webapp.after_request
def add_header(r):
  r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
  r.headers["Pragma"] = "no-cache"
  r.headers["Expires"] = "0"
  r.headers['Cache-Control'] = 'public, max-age=0'
  return r


# ***** main event loop *****

watering = False
watering_start = 0

def start_watering(reason):
  global watering
  global watering_start
  if not watering:
    watering = True
    watering_start = time.perf_counter()
    water(True, reason)

def end_watering(reason):
  global watering
  global watering_start
  if watering:
    watering = False
    watering_start = 0
    water(False, reason)

# When is the next sensed watering event (as a string)?
def get_next_sensor_str():
  sensor = config['sensor']
  if not sensor:
    return ''
  dry = config['dry']
  return 'when moisture < ' + str(int(100 * (dry / 65535.0))) + '%'

# When is the next timed watering event?
def get_next_timer(now):

  timer = config['timer']
  if not timer:
    return datetime.fromtimestamp(0)
  days_str = config['days']
  when_str = config['when']
  debug(DEBUG_NEXT_WHEN, "WHEN=" + when_str)
  today_str = now.strftime("%d/%m/%Y")
  debug(DEBUG_NEXT_WHEN, "today=" + today_str)
  when_today = datetime.strptime(today_str + ' ' + when_str, '%d/%m/%Y %I:%M%p')
  debug(DEBUG_NEXT_WHEN, "when=" + when_today.strftime('%a, %b%-d, %-I:%M%p'))
  when_tomorrow = datetime.strptime(today_str + ' ' + when_str, '%d/%m/%Y %I:%M%p') + timedelta(days=1)
  when_day_after_tomorrow = datetime.strptime(today_str + ' ' + when_str, '%d/%m/%Y %I:%M%p') + timedelta(days=2)

  # All days
  if 'all' == days_str:
    # Water later today
    if now < when_today:
      debug(DEBUG_NEXT, "[all] --> today")
      return when_today
    # Water tomorrow
    else:
      debug(DEBUG_NEXT, "[all] --> tomorrow")
      return when_tomorrow

  # Odd days
  odd_today = (int(now.strftime("%d")) % 2) == 1
  odd_tomorrow = (int(when_tomorrow.strftime("%d")) % 2) == 1
  odd_day_after_tomorrow = (int(when_day_after_tomorrow.strftime("%d")) % 2) == 1
  if odd_today and 'odd' == days_str:
    # Water later today
    if now < when_today:
      debug(DEBUG_NEXT, "[odd] --> today")
      return when_today
    # Water next odd day (which could be 1 or 2 days away)
    elif odd_tomorrow:
      debug(DEBUG_NEXT, "[odd] --> tomorrow")
      return when_tomorrow
    else:
      debug(DEBUG_NEXT, "[odd] --> day after tomorrow")
      return when_day_after_tomorrow
  elif (not odd_today) and 'odd' == days_str:
    return when_tomorrow

  # Even days
  even_today = not odd_today
  even_tomorrow = not odd_tomorrow
  even_day_after_tomorrow = not odd_day_after_tomorrow
  if even_today and 'even' == days_str:
    # Water later today
    if now < when_today:
      debug(DEBUG_NEXT, "[even] --> today")
      return when_today
    # Water next even day (which could be 2 or 3 days away)
    elif even_day_after_tomorrow:
      debug(DEBUG_NEXT, "[even] --> day after tomorrow")
      return when_day_after_tomorrow
    else:
      debug(DEBUG_NEXT, "[even] --> day after the day after tomorrow")
      return when_today + timedelta(days=3)
  elif (not even_today) and 'even' == days_str:
    if even_tomorrow:
      debug(DEBUG_NEXT, "[even] --> tomorrow")
      return when_tomorrow
    else:
      debug(DEBUG_NEXT, "[even] --> day after tomorrow")
      return when_day_after_tomorrow

def get_next_timer_str(now):
  timer = config['timer']
  if not timer:
    return ''
  when = get_next_timer(now)
  return when.strftime('%a %b %-d, %-I:%M%p')

button_down = False
button_start = 0
last_sensor_watering = datetime.fromtimestamp(0)
startup = datetime.now().strftime('%d/%m/%Y %I:%M%p')
log('{"startup":"' + startup + '"}')
while (True):

  # Only call this once per loop to avoid inconsistencies as time changes
  now = datetime.now()

  # Does the sensor think we should we be watering right now?
  sensor = config['sensor']
  if sensor and not watering:
    if moisture.value <= config['dry']:
      debug(DEBUG_SENSOR, "Sensor is DRY!")
      cooldown_min = config['cooldown_min']
      earliest = last_sensor_watering + timedelta(minutes=cooldown_min)
      if now >= earliest:
        debug(DEBUG_WATERING, "Sensor is triggering watering...")
        last_sensor_watering = now
        start_watering('sensor')
      else:
        debug(DEBUG_SENSOR, "Sensor is in cooldown...")

  # Does the timer think we should we be watering right now?
  timer = config['timer']
  if timer and not watering:
    next = get_next_timer(now)
    if now < next and now + timedelta(seconds=(2 * SLEEP_SEC)) > next:
      debug(DEBUG_WATERING, 'Timer is triggering watering...')
      start_watering('timer')

  # Button transitioning to down state?
  if (not button_down) and GPIO.input(PIN_PUSHBUTTON) == GPIO.HIGH:
    debug(DEBUG_BUTTON, "Button going DOWN!")
    button_down = True
    button_start = time.perf_counter()
  # Button transitioning to up state?
  elif button_down and GPIO.input(PIN_PUSHBUTTON) == GPIO.LOW:
    debug(DEBUG_BUTTON, "Button going UP!")
    button_down = False
    duration = time.perf_counter() - button_start
    if duration >= LONG_PRESS_SEC:
      debug(DEBUG_BUTTON, "Button long press (d=%f)" % duration)
      debug(DEBUG_WATERING, "Button is triggering watering...")
      start_watering('button')
    else:
      debug(DEBUG_BUTTON, "Button short press (d=%f)" % duration)
      debug(DEBUG_WATERING, "Button is stopping watering...")
      end_watering('button')

  # End watering after the specified time
  if watering and time.perf_counter() - watering_start > config['duration_sec']:
    debug(DEBUG_WATERING, "Watering time elapsed.")
    end_watering('timer')
  
  # Clear the screen by drawing a full-sized black rectangle as background
  draw.rectangle((0, 0, oled.width, oled.height), outline=0, fill=0)

  # Show this machine's IP address on the top line of the display (yellow)
  text_centered_y(0, 'ADDR: ' + LOCAL_IP_ADDRESS)

  # Show date and time on the second line of the display
  text_centered_y(14, now.strftime('%a %b %-d, %-I:%M:%S%p'))

  # Show watering status next, if watering is happening now
  if watering:
    duration = str(int(time.perf_counter() - watering_start))
    text_centered_y(30, 'WATERING: ' + duration + 's')
  else:
    # Otherwise, give info about the next watering event (sensor or timer)
    text_xy(0, 30, 'Next watering:')
    text_xy(0, 40, '  ' + get_next_sensor_str() + get_next_timer_str(now))
    text_xy(0, 50, ' ')

  # And finish up the display with the moisture sensor output
  text_centered_y(54, 'Moisture: ' + str(int(100 * (moisture.value / 65535.0))) + '%')

  # Display the resulting image (after all the above drawing)
  oled.image(image)
  oled.show()

  # Sleep briefly (to not to hog too much CPU)
  time.sleep(SLEEP_SEC)


