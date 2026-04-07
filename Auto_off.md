# HVAC Auto-Off Timer for Home Assistant
This automation allows you to set a dynamic "Sleep Timer" for your air conditioning zones. Instead of a fixed time, you can adjust the countdown duration (in hours) directly from your dashboard using a slider.

## How it Works
You move a slider (input_number) to a value (e.g., 3).
The automation triggers and waits for that many hours.
Once the time expires, the associated HVAC zone turns off.
The slider automatically resets to 0.  
*Note: If you change the slider while a timer is running, the timer restarts with the new value*

## 1. Prerequisites (Create the Helpers)
You need to create an input_number helper for every room you want to control.
1. Go to Settings > Devices & Services > Helpers.
2. Click Create Helper > Number.
3. Use the following settings for each room:
    * Name: Climate Off xxxx (where xxxx is the controller for this helper (e.g living, master or guest))
    * Minimum value: 0
    * Maximum value: 12 (or your preferred max hours)
    * Step size: 1
    * Display mode: Slider
    * Unit of measurement: h

**Important:** Make sure the Entity IDs match those in the automation:
```
input_number.climate_off_living
input_number.climate_off_master
input_number.climate_off_guest
```
## 2. Installation
Copy the following code into your automations.yaml file or create a new automation in the UI using the YAML editor.

```YAML
alias: "Climate - Turn off after X hours"
id: 'climate_auto_off_timer'
description: "Dynamically turns off HVAC zones based on input_number sliders"
triggers:
  - trigger: state
    entity_id:
      - input_number.climate_off_living
      - input_number.climate_off_master
      - input_number.climate_off_guest
conditions:
  # Only run if the slider is set to a value greater than 0
  - condition: template
    value_template: "{{ trigger.to_state.state | int > 0 }}"
actions:
  - variables:
      hours: "{{ states(trigger.entity_id) | int }}"
      climate_map:
        input_number.climate_off_living: climate.living_room # or the name of the AC controller for this input number
        input_number.climate_off_master: climate.master_bedroom # or the name of the contoller for this input number
        input_number.climate_off_guest: climate.smarttemp_system # or the name of this controller for this input number
  
  # Wait for the number of hours selected on the slider
  - delay:
      hours: "{{ hours }}"
  
  # Turn off the associated HVAC entity
  - action: climate.set_hvac_mode
    target:
      entity_id: "{{ climate_map[trigger.entity_id] }}"
    data:
      hvac_mode: 'off'
  
  # Reset the slider back to 0
  - action: input_number.set_value
    target:
      entity_id: "{{ trigger.entity_id }}"
    data:
      value: 0
mode: restart
```
## 3. Configuration / Mapping
If your HVAC entity names are different, look at the climate_map section in the variables:
- Change climate.living_room to match your actual Home Assistant entity name.
- Ensure the input_number on the left matches the one on the right.

## 4. Dashboard Setup
Add the sliders to your Lovelace dashboard for easy access:

```YAML
type: entities
title: HVAC Sleep Timers
entities:
  - entity: input_number.climate_off_living
    name: Living Room Timer
  - entity: input_number.climate_off_master
    name: Master Bedroom Timer
  - entity: input_number.climate_off_guest
    name: Guest Room Timer
```
*Tip: Make the lovelace Tile card configuration only visible when the AC is on.*
## Troubleshooting
- **Timer doesn't stop:** If you manually turn the AC off, the timer will still run and eventually try to send the "off" command again. This is harmless.
- **Manual Override:** To cancel a timer, simply move the slider back to 0. (The automation condition > 0 will prevent it from starting a new wait).