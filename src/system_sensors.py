#!/usr/bin/env python3
import argparse
import datetime as dt
import signal
import sys
import socket
import platform
import threading
import time
from datetime import timedelta
from re import findall
from subprocess import check_output
from rpi_bad_power import new_under_voltage
import paho.mqtt.client as mqtt
import psutil
import pytz
import yaml
import csv
from pytz import timezone

try:
    import apt
    apt_disabled = False
except ImportError:
    apt_disabled = True
UTC = pytz.utc
DEFAULT_TIME_ZONE = None

old_net_data = psutil.net_io_counters()
previous_time = time.time()

# Get OS information
OS_DATA = {}
with open("/etc/os-release") as f:
    reader = csv.reader(f, delimiter="=")
    for row in reader:
        if row:
            OS_DATA[row[0]] = row[1]

mqttClient = None
WAIT_TIME_SECONDS = 60
deviceName = None
_underVoltage = None

class ProgramKilled(Exception):
    pass


def signal_handler(signum, frame):
    raise ProgramKilled


class Job(threading.Thread):
    def __init__(self, interval, execute, *args, **kwargs):
        threading.Thread.__init__(self)
        self.daemon = False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self.stopped.set()
        self.join()

    def run(self):
        while not self.stopped.wait(self.interval.total_seconds()):
            self.execute(*self.args, **self.kwargs)


def write_message_to_console(message):
    print(message)
    sys.stdout.flush()


def utc_from_timestamp(timestamp: float) -> dt.datetime:
    """Return a UTC time from a timestamp."""
    return UTC.localize(dt.datetime.utcfromtimestamp(timestamp))


def as_local(dattim: dt.datetime) -> dt.datetime:
    """Convert a UTC datetime object to local time zone."""
    if dattim.tzinfo == DEFAULT_TIME_ZONE:
        return dattim
    if dattim.tzinfo is None:
        dattim = UTC.localize(dattim)

    return dattim.astimezone(DEFAULT_TIME_ZONE)

def get_last_boot():
    return str(as_local(utc_from_timestamp(psutil.boot_time())).isoformat())

def get_last_message():
    return str(as_local(utc_from_timestamp(time.time())).isoformat())


def on_message(client, userdata, message):
    print (f"Message received: {message.payload.decode()}"  )
    if(message.payload.decode() == "online"):
        send_config_message(client)


def updateSensors():
    payload_str = (
        '{'
        + f'"temperature": {get_temp()},'
        + f'"disk_use": {get_disk_usage("/")},'
        + f'"memory_use": {get_memory_usage()},'
        + f'"cpu_usage": {get_cpu_usage()},'
        + f'"swap_usage": {get_swap_usage()},'
        + f'"last_boot": "{get_last_boot()}"'
    )

    payload_str = payload_str + "}"
    mqttClient.publish(
        topic=f"system-sensors/sensor/{deviceName}/state",
        payload=payload_str,
        qos=1,
        retain=False,
    )


def get_updates():
    cache = apt.Cache()
    cache.open(None)
    cache.upgrade()
    return str(cache.get_changes().__len__())


# Temperature method depending on system distro
def get_temp():
    temp = "";
    if "rasp" in OS_DATA["ID"]:
        reading = check_output(["vcgencmd", "measure_temp"]).decode("UTF-8")
        temp = str(findall("\d+\.\d+", reading)[0])
    else:
        reading = check_output(["cat", "/sys/class/hwmon/hwmon0/temp1_input"]).decode("UTF-8")
        temp = str(reading[0] + reading[1] + "." + reading[2])
    return temp

def get_disk_usage(path):
    return str(psutil.disk_usage(path).percent)


def get_memory_usage():
    return str(psutil.virtual_memory().percent)


def get_load(arg):
    return str(psutil.getloadavg()[arg])

def get_net_data():
    global old_net_data
    global previous_time
    current_net_data = psutil.net_io_counters()
    current_time = time.time()
    net_data = (current_net_data[0] - old_net_data[0]) / (current_time - previous_time) * 8 / 1024
    net_data = (net_data, (current_net_data[1] - old_net_data[1]) / (current_time - previous_time) * 8 / 1024)
    previous_time = current_time
    old_net_data = current_net_data
    return ['%.2f' % net_data[0], '%.2f' % net_data[1]]


def get_cpu_usage():
    return str(psutil.cpu_percent(interval=None))


def get_swap_usage():
    return str(psutil.swap_memory().percent)


def remove_old_topics():
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}Temp/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}DiskUse/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}MemoryUse/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}CpuUsage/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}SwapUsage/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/binary_sensor/{deviceNameDisplay}/{deviceNameDisplay}PowerStatus/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}PowerStatus/config",
        payload='',
        qos=1,
        retain=False,
    )
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceNameDisplay}/{deviceNameDisplay}LastBoot/config",
        payload='',
        qos=1,
        retain=False,
    )


def check_settings(settings):
    if "mqtt" not in settings:
        write_message_to_console("Mqtt not defined in settings.yaml! Please check the documentation")
        sys.exit()
    if "hostname" not in settings["mqtt"]:
        write_message_to_console("Hostname not defined in settings.yaml! Please check the documentation")
        sys.exit()
    if "timezone" not in settings:
        write_message_to_console("Timezone not defined in settings.yaml! Please check the documentation")
        sys.exit()
    if "deviceName" not in settings:
        write_message_to_console("deviceName not defined in settings.yaml! Please check the documentation")
        sys.exit()
    if "client_id" not in settings:
        write_message_to_console("client_id not defined in settings.yaml! Please check the documentation")
        sys.exit()
    if "power_integer_state" in settings:
        write_message_to_console("power_integer_state is deprecated please remove this option power state is now a binary_sensor!")


def send_config_message(mqttClient):
    write_message_to_console("send config message")
    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/temperature/config",
        payload='{"device_class":"temperature",'
                + f"\"name\":\"{deviceNameDisplay} Temperature\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"unit_of_measurement":"°C",'
                + '"value_template":"{{value_json.temperature}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_temperature\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:thermometer\"}}",
        qos=1,
        retain=True,
    )

    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/disk_use/config",
        payload=f"{{\"name\":\"{deviceNameDisplay} Disk Use\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"unit_of_measurement":"%",'
                + '"value_template":"{{value_json.disk_use}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_disk_use\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:micro-sd\"}}",
        qos=1,
        retain=True,
    )

    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/memory_use/config",
        payload=f"{{\"name\":\"{deviceNameDisplay} Memory Use\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"unit_of_measurement":"%",'
                + '"value_template":"{{value_json.memory_use}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_memory_use\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:memory\"}}",
        qos=1,
        retain=True,
    )

    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/cpu_usage/config",
        payload=f"{{\"name\":\"{deviceNameDisplay} Cpu Usage\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"unit_of_measurement":"%",'
                + '"value_template":"{{value_json.cpu_usage}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_cpu_usage\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:memory\"}}",
        qos=1,
        retain=True,
    )


    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/swap_usage/config",
        payload=f"{{\"name\":\"{deviceNameDisplay} Swap Usage\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"unit_of_measurement":"%",'
                + '"value_template":"{{value_json.swap_usage}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_swap_usage\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:harddisk\"}}",
        qos=1,
        retain=True,
    )

    mqttClient.publish(
        topic=f"homeassistant/binary_sensor/{deviceName}/power_status/config",
        payload='{"device_class":"problem",'
                + f"\"name\":\"{deviceNameDisplay} Under Voltage\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"value_template":"{{value_json.power_status}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_power_status\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}}"
                + f"}}",
        qos=1,
        retain=True,
    )


    mqttClient.publish(
        topic=f"homeassistant/sensor/{deviceName}/last_boot/config",
        payload='{"device_class":"timestamp",'
                + f"\"name\":\"{deviceNameDisplay} Last Boot\","
                + f"\"state_topic\":\"system-sensors/sensor/{deviceName}/state\","
                + '"value_template":"{{value_json.last_boot}}",'
                + f"\"unique_id\":\"{deviceName}_sensor_last_boot\","
                + f"\"availability_topic\":\"system-sensors/sensor/{deviceName}/availability\","
                + f"\"device\":{{\"identifiers\":[\"{deviceName}_sensor\"],"
                + f"\"name\":\"{deviceNameDisplay} Sensors\",\"model\":\"RPI {deviceNameDisplay}\", \"manufacturer\":\"RPI\"}},"
                + f"\"icon\":\"mdi:clock\"}}",
        qos=1,
        retain=True,
    )
    mqttClient.publish(f"system-sensors/sensor/{deviceName}/availability", "online", retain=True)


def _parser():
    """Generate argument parser"""
    parser = argparse.ArgumentParser()
    parser.add_argument("settings", help="path to the settings file")
    return parser


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        write_message_to_console("Connected to broker")
        client.subscribe("hass/status")
        mqttClient.publish(f"system-sensors/sensor/{deviceName}/availability", "online", retain=True)
    else:
        write_message_to_console("Connection failed")


if __name__ == "__main__":
    args = _parser().parse_args()
    with open(args.settings) as f:
        # use safe_load instead load
        settings = yaml.safe_load(f)
    check_settings(settings)
    DEFAULT_TIME_ZONE = timezone(settings["timezone"])
    if "update_interval" in settings:
        WAIT_TIME_SECONDS = settings["update_interval"]
    mqttClient = mqtt.Client(client_id=settings["client_id"])
    mqttClient.on_connect = on_connect                      #attach function to callback
    mqttClient.on_message = on_message
    deviceName = settings["deviceName"].replace(" ", "").lower()
    deviceNameDisplay = settings["deviceName"]
    mqttClient.will_set(f"system-sensors/sensor/{deviceName}/availability", "offline", retain=True)
    if "user" in settings["mqtt"]:
        mqttClient.username_pw_set(
            settings["mqtt"]["user"], settings["mqtt"]["password"]
        )  # Username and pass if configured otherwise you should comment out this
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    if "port" in settings["mqtt"]:
        mqttClient.connect(settings["mqtt"]["hostname"], settings["mqtt"]["port"])
    else:
        mqttClient.connect(settings["mqtt"]["hostname"], 1883)
    try:
        remove_old_topics()
        send_config_message(mqttClient)
    except:
        write_message_to_console("something whent wrong")
    _underVoltage = new_under_voltage()
    job = Job(interval=timedelta(seconds=WAIT_TIME_SECONDS), execute=updateSensors)
    job.start()

    mqttClient.loop_start()

    while True:
        try:
            sys.stdout.flush()
            time.sleep(1)
        except ProgramKilled:
            write_message_to_console("Program killed: running cleanup code")
            mqttClient.publish(f"system-sensors/sensor/{deviceName}/availability", "offline", retain=True)
            mqttClient.disconnect()
            mqttClient.loop_stop()
            sys.stdout.flush()
            job.stop()
            break
