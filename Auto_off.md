# HVAC Auto-Off Timer for Home Assistant
This automation allows you to set a dynamic "Sleep Timer" for your air conditioning zones. Instead of a fixed time, you can adjust the countdown duration (in hours) directly from your dashboard using a slider.

## How it Works
You move a slider (input_number) to a value (e.g., 3).
The automation triggers and waits for that many hours.
Once the time expires, the associated HVAC zone turns off.
The slider automatically resets to 0.  
*Note: If you change the slider while a timer is running, the timer restarts with the new value*

## 1. Prerequisites
### 1.1 Create the Helpers
You need to create an input_number helper for every HVAC zone you want to control.
1. Go to Settings > Devices & Services > Helpers.
2. Click Create Helper > Number.
3. Use the following settings for each room:
    * Name: "climate_off_xxxx" *where xxxx is the HVAC zone for this helper (e.g living, master or guest)*
    * Minimum value: 0
    * Maximum value: 12 (or your preferred max hours)
    * Step size: 1
    * Display mode: Slider
    * Unit of measurement: hours
4. Repeat for each HVAC zone you want to control.

**Example:** You should now have a number of helper entities like:
```
input_number.climate_off_living
input_number.climate_off_master
input_number.climate_off_guest
```
Note the name of these entities as they need to match the name in the Automation below.  
### 1.2 Configuration / Mapping
Get the climate Entity ID for each HVAC unit that you have created an input_number helper for.  
The Climate Entity ID name can be found by going to the Smarttemp Integration, clicking on each controller where you will see a "Controls" panel. Clicking on each control will bring up the climate controls for that zone. In the top right is a "cog" symbol. Clicking on the cog will reveal the Entity ID (as well as other details).  
Note the mapping of each "input_number" helper with the associated climate Entity ID.
## 2. Automation Installation
1. In Home Assistant got to **Settings > Automations & scenes**.  
2. Select "**+ Create Automation**" and then select "**Create new automation**"
3. Click on the 3 vertical dots on the top right corner of the page, and select "**Edit in YAML**"
4. Paste in the following code (replacing any existing code):
```YAML
alias: 'climate_auto_off_timer'
description: "Dynamically turns off HVAC zones based on input_number sliders"
triggers:
  - trigger: state
    entity_id:
    # Add the names of the Helpers created above
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
      # For each Helper, create a link between the helper and the associated HVAC zone name.
      # For Example:
        input_number.climate_off_living: climate.living_room 
        input_number.climate_off_master: climate.master_bedroom 
        input_number.climate_off_guest: climate.smarttemp_system 
  
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
5. Save the Automation.  

**Note:** when you save the YAML, Home Assistant will strip out the comments

## 3. Dashboard Setup
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
Alternately, using the UI:
1. Go to your dashboard and click on the "edit dashboard" pen (top right)
2. Add a Tile Card *(Tip: add it directly under your climate controls for that zone)*
3. In the Tile Card configuration:
    * **Config**
        * Entity: your "input_number" entity *(eg. input.number-climate_off_living)*
        * Content:
            * Name: "Custom" - Enter "Turn off after:"
            * Icon: select an appropriate icon *(e.g.mdi_airconditioner)*
        * Features: 
            * Select Features position : Inline
            * Add feature "Numeric Input", edit this and select "Slider"
    * **Visibility** *(optional)*
      * Select "Add Condition" > "Entity State"
      * Entity: ENter than ame of the AC control Entity (e.g. climate.living_room)
      * State: Select "State is **not** equal to"
      * State: Select "off"
  4. Save the tile

The optional "Visibility" condition makes the lovelace Tile card configuration only visible when the zone is on.
## Troubleshooting
- **Manual Override:** To cancel a timer, simply move the slider back to 0. (The automation condition > 0 will prevent it from starting a new wait).