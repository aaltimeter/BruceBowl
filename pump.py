from gpiozero import OutputDevice
from time import sleep

pump = OutputDevice(17, initial_value=False)

print("Pump ON")
pump.on()
sleep(3)

print("Pump OFF NIgga")
pump.off()
