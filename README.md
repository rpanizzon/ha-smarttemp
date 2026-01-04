
# Smart Temp Inspire Touch Air Conditioner controller - HA Custom Component
Home Assistant custom component that creates an alterante server to the cloud based Smarttemp server (smarttempapp.com.au)
This was developed by analysing the tcp traffic between the smarttemp controller and the cloud based server.
Note, this integration replaces the cloud based server with Home Assistant, making the Smarttemp app unable to access the controller and therefore unusable. Use Home Assistant app instead.


## Features
- Local TCP control
- Per-zone climate entities
- No cloud dependency
- Home Assistant handles scheduling
**This is a work-in-progress!** 

## Protocol

## Setup
You must have a local DNS installed to redirec the controller(s) to Home Assistant
The recommended appoach is to use a local DNS such as Adguard or Pi-Hole and redirect "smarttempapp.com.au" to Home Assistant.

## Installation
1. Copy `custom_components/smarttemp` into your HA config directory
2. Restart Home Assistant
3. Add integration via Settings → Devices & Services

### Configuration.yaml 
    smarttemp:
      username: "username"
      password: "password"
### Restart HA
Once you've complete the above steps, restart Home Assistant. Once restarted, You should see entries appear in the integration. There should be 1 entry per zone/controller.

## Status
Early development

### Contolling AC units from Home Assistant


### Issues

        
### Functionality / To-Do 
See the [Issues List](https://github.com/rpanizzon/ge-smarttemp/issues) for a complete list of know issues/requests.
 - Climate
    - [ ] Fix Time issues
    - [ ] is hub processing time and weather commands?
    _ [ ] Check out malformed JSON
    - [ ] no temperature set
    - [ ] fix commands to fan
    _ [ ] rationalise entities
    - [ ] no autoofftime
 - Sensors
    - [ ] 
 - [ ] Update Documentation
 -     [ ]  Readme
 -     [ ]  Protocol Document



 