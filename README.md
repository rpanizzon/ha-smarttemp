
# Smart Temp Inspire Touch Air Conditioner controller - HA Custom Component
Home Assistant custom component that creates an alterante server to the cloud based Smarttemp server (smarttempapp.com.au)
This was developed by analysing the tcp traffic between the smarttemp controller and the cloud based server.
Note, this integration replaces the cloud based server with Home Assistant, making the Smarttemp app unable to access the controller and therefore unusable. Use Home Assistant app instead.

This integration requests all devices linked to your Smart Temp account and automatically adds them into Home Assistant.

## Features
- Local TCP control
- Per-zone climate entities
- No cloud dependency
- Home Assistant handles scheduling


**This is a work-in-progress!** 

## Setup

The Inspire Touch AC control unit communicates with . Once you've created an account and can successfully control the unit from the app, you can use your login details with this integration. 
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
Once you've complete the above steps, restart Home Assistant. Once restarted, ???.

## Status
Early development

### Contolling AC units from Home Assistant


### Issues

        
### Functionality / To-Do 
See the [Projects board](https://github.com/users/rpanizzon/smarttemp) for updated list.
 - [ ] HTTP: Get Websocket status and API Key.
 - [ ] WS: Login using API Key.
 - [ ] Obtain ongoing status for each Inspire Touch Controller
 - [ ] Change setting on Unit:
 -     [ ]  Switch unit on and off
 -     [ ]  Set Mode
 -     [ ]  Set Temperature
 -     [ ]  Set Zone


 