from gpiozero import LED, Button
from time import sleep
from signal import pause

led = LED(17)
button = Button(27, pull_up=True, bounce_time=0.05)

def button_pressed():
    print("BUTTON PRESSED")
    print("LED ON")

    led.on()
    sleep(5)
    led.off()

    print("LED OFF")

button.when_pressed = button_pressed

print("Ready - press the button")
pause()
