# System sensors for Debian and Raspbian


I’ve folk this code and add some file to suitable with more machine (debian, armbian, raspbian)

It currently logs the following data:
* CPU usage
* CPU temperature
* Disk usage
* Memory usage
* Power status (Undervoltage)
* Last boot
* Swap usage


# System Requirements

You need to have at least __python 3.6__ installed to use System Sensors.

# Installation:
1. Clone this repo >> git clone https://github.com/anhtuanng98/system_sensors.git
2. cd system_sensors
3. pip3 install -r requirements.txt
4. sudo apt-get install python3-apt
5. Edit settings_example.yaml in "~/system_sensors/src" to reflect your setup and save as settings.yaml:

| Value  | Required | Default | Description | 
| ------------- | ------------- | ------------- | ------------- |
| hostname  | true | \ | Hostname of the MQTT broker
| port  | false | 1883 | Port of the MQTT broker
| user | false | \ | The userlogin( if defined) for the MQTT broker
| password | false | \ | the password ( if defined) for the MQTT broker
| deviceName | true | \ | device name is sent with topic
| client_id | true | \ | client id to connect to the MQTT broker
| timezone | true | \ | Your local timezone (you can find the list of timezones here: [time zones](https://gist.github.com/heyalexej/8bf688fd67d7199be4a1682b3eec7568))
| power_integer_state(Deprecated) | false | false | Deprecated
| update_interval | false | 60 | The update interval to send new values to the MQTT broker 

Example:
| Value  | Required | Default | Description | 
| ------------- | ------------- | ------------- | ------------- |
| hostname  | true | \ | 192.168.1.50
| port  | false | 1883 | Port of the MQTT broker
| user | false | \ | mqtt_user_id
| password | false | \ | mqtt_user_passwd
| deviceName | true | \ | Name_of_device
| client_id | true | \ | id_of_device (eg: tx3_mini_pc)
| timezone | true | \ | Your local timezone (you can find the list of timezones here: [time zones](https://gist.github.com/heyalexej/8bf688fd67d7199be4a1682b3eec7568))
| update_interval | false | 60 | The update interval to send new values to the MQTT broker 

6. python3 src/system_sensors.py src/settings.yaml
7. (optional) create service to autostart the script at boot:
    
a. With Raspbian:
    1. sudo cp system_sensors_rpi.service /etc/systemd/system/system_sensors_rpi.service
    2. sudo systemctl enable system_sensors_rpi.service
    3. sudo systemctl start system_sensors_rpi.service
b. With Debian/Armbian:
    1. sudo cp system_sensors_armbian.service /etc/systemd/system/system_sensors_armbian.service
    2. sudo systemctl enable system_sensors_armbian.service
    3. sudo systemctl start system_sensors_armbian.service


# Home Assistant configuration:
## Configuration:
The only config you need in Home Assistant is the following:
```yaml
mqtt:
  discovery: true
  discovery_prefix: homeassistant
```

## Lovelace UI example:
I have used following custom plugins for lovelace:
* vertical-stack-in-card
* mini-graph-card
* bar-card

Config:
```yaml
- type: 'custom:vertical-stack-in-card'
    title: Deconz System Monitor
    cards:
      - type: horizontal-stack
        cards:
          - type: custom:mini-graph-card
            entities:
              - sensor.deconz_cpu_usage
            name: CPU
            line_color: '#2980b9'
            line_width: 2
            hours_to_show: 24
          - type: custom:mini-graph-card
            entities:
              - sensor.deconz_temperature
            name: Temp
            line_color: '#2980b9'
            line_width: 2
            hours_to_show: 24
      - type: custom:bar-card
        entity: sensor.deconz_disk_use
        title: HDD
        title_position: inside
        align: split
        show_icon: true
        color: '#00ba6a'
      - type: custom:bar-card
        entity: sensor.deconz_memory_use
        title: RAM
        title_position: inside
        align: split
        show_icon: true
      - type: entities
        entities:
          - sensor.deconz_last_boot
          - sensor.deconz_under_voltage
```
Example:

![alt text](images/example.png?raw=true "Example")

[releases]: https://github.com/anhtuanng98/system_sensors/releases
