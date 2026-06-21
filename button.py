from gpiozero import LED
from time import sleep

led = LED(17)

while True:
    command = input("Type on, off, fast, blink, slow, or quit: ")

    if command == "on":
        led.on()

    elif command == "off":
        led.off()

    elif command == "fast":
        print("Fast blink mode")
        while True:
            led.on()
            sleep(0.25)
            led.off()
            sleep(0.25)

    elif command == "blink":
        print("Normal blink mode")
        while True:
            led.on()
            sleep(0.5)
            led.off()
            sleep(0.5)

    elif command == "slow":
        print("Slow blink mode")
        while True:
            led.on()
            sleep(1)
            led.off()
            sleep(1)

    elif command == "quit":
        led.off()
        break

    else:
        print("Unknown command")
