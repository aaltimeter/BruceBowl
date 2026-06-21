from gpiozero import OutputDevice
from time import sleep

pump = OutputDevice(17, initial_value=False)

def dispense(seconds):
    pump.on()
    sleep(seconds)
    pump.off()

dispense(10)
