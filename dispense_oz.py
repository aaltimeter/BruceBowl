from gpiozero import OutputDevice
from time import sleep

pump = OutputDevice(17, initial_value=False)

ML_PER_SECOND = 22.1
ML_PER_OZ = 29.57

def dispense_oz(ounces):
    ml_needed = ounces * ML_PER_OZ
    seconds = ml_needed / ML_PER_SECOND

    print(f"Dispensing {ounces} oz for {seconds:.2f} seconds")
    pump.on()
    sleep(seconds)
    pump.off()
    print("Done")

dispense_oz(4)
