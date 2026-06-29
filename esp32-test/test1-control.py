import network
import time
import ufirebase as firebase
from ds3231 import DS3231
from hx711 import HX711
from pzem import get_pzem, calc_bill 
from machine import Pin, SoftI2C, reset
from lcd_api import LcdApi
from i2c_lcd import I2cLcd
import _thread

import json

# ตั้งค่าขาพิน
kettle_pin = Pin(4, Pin.OUT)
kettle_pin.value(0)

# ตั้งค่า DS3231
i2c = SoftI2C(scl=Pin(21), sda=Pin(22), freq=10000)
lcd = I2cLcd(i2c, 0x27, 4, 20)
rtc = DS3231(i2c)  # ใช้ i2c ตัวเดียวกัน

# อ่านค่าจาก DS3231:  return (year, month, day, weekday, hour, min, sec, 0)
#                index:    [0]    [1]   [2]    [3]   [4]  [5]  [6] [7]
# ตั้งค่า DS3231:  rtc.datetime((year, month, day, hour, min, sec, weekday))
#                index:                  [0]    [1]  [2]  [3]  [4]  [5]   [6]

keyMatrix = [
    ["1","2","3","A"],
    ["4","5","6","B"],
    ["7","8","9","C"],
    ["*","0","#","D"]
]
# rowPins = [13,12,14,27]  
# colPins = [26,25,33,32]
# row    = [Pin(p, mode=Pin.OUT)                    for p in rowPins]
# column = [Pin(p, mode=Pin.IN, pull=Pin.PULL_DOWN) for p in colPins]
COLS = [Pin(p, Pin.OUT) for p in [26,25,33,32]]
ROWS = [Pin(p, Pin.IN, Pin.PULL_DOWN) for p in [13,12,14,27]]

hx = HX711(dout=34, pd_sck=23)
hx.set_offset(8565663.0)
hx.set_scale(111.59)

# เชื่อมต่อ WiFi
wlan = network.WLAN(network.STA_IF)
wlan.active(False)
wlan.active(True)

# ผูกกับ Firebase
#FIREBASE_URL = "kettle-control-default-rtdb.asia-southeast1.firebasedatabase.app"
#firebase.setURL(FIREBASE_URL)

firebase.setURL("https://kettle-control-default-rtdb.asia-southeast1.firebasedatabase.app/")

def _read_dt():
    """อ่านค่าจาก DS3231 แล้ว return dict"""
    dt = rtc.datetime()
    return {
        "year": dt[0], "mon": dt[1], "day": dt[2],
        "weekday": dt[3], "hour": dt[4], "min": dt[5], "sec": dt[6]
    }

def _set_dt(year, mon, day, hour, min, sec, weekday=0):
    """ตั้งค่า DS3231"""
    rtc.datetime((year, mon, day, hour, min, sec, weekday))

def scanKeypad():
    """สแกน keypad และคืนค่าปุ่มที่กด หรือ None"""
    for c, col in enumerate(COLS):
        col.value(1)
        for r, row in enumerate(ROWS):
            val = row.value()
            if val:
                print("col:", c, "row:", r, "key:", keyMatrix[r][c])  # ← เห็นค่าที่อ่านได้
        key = next((keyMatrix[r][c] for r, row in enumerate(ROWS) if row.value()), None)
        col.value(0)
        if key:
            time.sleep_ms(200)
            return key
    return None

def read_num():
    num = ""
    while True:
        key = scanKeypad()
        if key is not None:
            if "0" <= key <= "9":
                lcd.putstr(key)
                num += key
                time.sleep(0.2)
                
            elif key == "A":
                if len(num) > 0:  # ตรวจสอบก่อนว่ามีตัวเลขให้ลบไหม
                    num = num[:-1]  # ลบตัวท้ายสุดในตัวแปรออก
                    
                    # --- ส่วนของการลบบนหน้าจอ LCD ---
                    # 1. หาตำแหน่งเคอร์เซอร์ปัจจุบัน (แถวและคอลัมน์ปัจจุบัน)
                    current_col = lcd.cursor_x
                    current_row = lcd.cursor_y
                    
                    if current_col > 0:
                        # ถอยกลับไป 1 ช่อง แล้วพิมพ์ช่องว่างทับ จากนั้นถอยกลับมาที่เดิม
                        lcd.move_to(current_col - 1, current_row)
                        lcd.putstr(" ")
                        lcd.move_to(current_col - 1, current_row)
                time.sleep(0.2)   # ใส่ delay กันการกดซ้อนกันซ้ำๆ
                
            elif key == "#":
                return int(num) if num else 0
            elif key == "*":
                return 0


def wait_keypress():
    while True:
       key=scanKeypad()
       if key is not None :
           break

# ============================================================
# ฟังก์ชันทั้งหมด
# ============================================================
def connect_wifi(ssid, password):
    global command
    lcd.clear()
    lcd.putstr("Connecting...")    
    wlan.connect(ssid, password)
    timeout = 0
    while not wlan.isconnected():
        print("connect_wifi: waiting...", timeout)
        time.sleep(0.5)
        timeout += 1
        if timeout > 20:
            print("connect_wifi: timeout!")
            command = f"6,0"
            return
    command = "6,1"         
    

def show_status():
    lcd.clear()
    time.sleep_ms(10)  
    d = _read_dt()
    time.sleep_ms(10)
    
    weight = hx.get_grams(times=1)
    weight = weight if weight is not None else 0
    net_weight = weight - data_system.get("kettle_weight", 0)
    net_weight = max(round(net_weight / 1000, 3), 0)
    
    kettle_state = "ON " if kettle_pin.value() else "OFF"
    lcd.move_to(0, 0)
    lcd.putstr("Date:{:04d}/{:02d}/{:02d}".format(d["year"], d["mon"], d["day"]))
    lcd.move_to(0, 1)
    lcd.putstr("Time:{:02d}:{:02d}:{:02d}    ".format(d["hour"], d["min"], d["sec"]))
    lcd.move_to(0, 2)
    lcd.putstr("Kettle:{}".format(kettle_state))
    lcd.move_to(0, 3)
    lcd.putstr("W:{:.1f}L".format(net_weight))
    lcd.move_to(12, 3)
    lcd.putstr("Menu[*]")       

def fn_get_datetime():
    global command
    
    d = _read_dt()
    command = f"1,{d['year']},{d['mon']},{d['day']},0,{d['hour']},{d['min']},{d['sec']}"    

def fn_set_date():    
    global command
    
    year = int(command[1])
    mon  = int(command[2])
    day  = int(command[3])
    d = _read_dt()  # เอาเวลาปัจจุบันมาใช้
    _set_dt(year, mon, day, d["hour"], d["min"], d["sec"], d["weekday"])
    command = f"2,OK!" 

def fn_set_time():    
    global command
    
    hour = int(command[1])
    min  = int(command[2])
    sec  = int(command[3])
    d = _read_dt()  # เอาวันที่ปัจจุบันมาใช้
    _set_dt(d["year"], d["mon"], d["day"], hour, min, sec, d["weekday"])
    # ส่งค่าที่ตั้งไปกลับทันที ไม่ต้องอ่านจาก DS3231 ใหม่
    command = f"3,OK!"
        
def fn_get_wifi_info():
    global command
    
    command = f"4,{data_system['ssid']},{data_system['password']}"
        
    
def fn_wifi_control():
    global command, data_system
    
    if command[1] == "1":
        data_system['connect_status'] = 1
        connect_wifi(data_system['ssid'], data_system['password'])    
    elif command[1] == "0":
        data_system['connect_status'] = 0        
        wlan.disconnect()        
        lcd.clear()
        command = f"6,0"        
    write_json()
        
def fn_kettle_control():
    global command
    
    if command[1] == "1":
        kettle_pin.value(1)
        command = f"7,1"        
    elif command[1] == "0":
        kettle_pin.value(0)
        command = f"7,0"        
    
    
def fn_get_kettle_status():
    global command
    
    if kettle_pin.value() == 1:
        command = f"8,1"
    else:
        command = f"8,0"      

def fn_set_zero():
    global command
    hx.tare()
    weight = hx.get_grams(times=16)
    weight = weight if weight is not None else 0
    command = "9,{:.1f}".format(weight)
    
def fn_set_kettle_weight():
    global command, data_system
    
    weight = hx.get_grams(times=16)
    weight = weight if weight is not None else 0
    data_system["kettle_weight"] = round(weight, 1)
    write_json()
    command = "10,{:.1f}".format(weight)

def fn_get_weight():
    global command
    weight = data_system.get("kettle_weight", 0)
    kg = round(weight / 1000, 3)
    command = "11,{:.3f}".format(kg)
    
def fn_get_current_water():
    global command, data_system
    
    weight = hx.get_grams(times=16)
    weight = weight if weight is not None else 0
    net_weight = weight - data_system.get("kettle_weight", 0)
    net_weight = max(round(net_weight, 1), 0)
    litre = round(net_weight / 1000, 3)
    data_system["current_water"] = litre   # เก็บค่าไว้ใน data_system
    command = "12,{:.3f}".format(litre)
    
def fn_set_before_water():
    global command, data_system
    
    weight = hx.get_grams(times=16)
    weight = weight if weight is not None else 0
    net_weight = round(weight - data_system.get("kettle_weight", 0), 1)
    net_weight = max(net_weight, 0)
    data_system["before_water"] = net_weight
    write_json()
    command = "13,{:.1f}".format(net_weight)
    
def fn_get_before_water():
    global command, data_system
    
    before_water = data_system.get("before_water", 0)
    litre = round(before_water / 1000, 3)
    command = "14,{:.2f}".format(litre)
    
def fn_get_energy():
    global command
    v, i, p, e, f, pf = get_pzem()
    bill = calc_bill(e)
    v   = v   if v   is not None else 0
    i   = i   if i   is not None else 0
    p   = p   if p   is not None else 0
    e   = e   if e   is not None else 0
    f   = f   if f   is not None else 0
    pf  = pf  if pf  is not None else 0
    command = f"15,{v},{i},{p},{e},{f},{pf},{bill:.2f}"
    
    
fb_result = ""
fb_done = False
fb_busy = False

def _fb_worker(path, var_name):
    global fb_result, fb_done, fb_busy
    try:
        firebase.get(path, var_name, bg=0)
        fb_result = getattr(firebase, var_name, "")
    except Exception as e:
        print("Firebase Error:", e)
        fb_result = ""
    fb_done = True
    fb_busy = False

def fb_get_start(path, var_name):
    global fb_done, fb_busy
    if fb_busy:
        return
    fb_done = False
    fb_busy = True
    _thread.start_new_thread(_fb_worker, (path, var_name))


  
    
    
timer_on_h   = 0
timer_on_m   = 0
timer_off_h  = 0
timer_off_m  = 0

def start_timer(on_h, on_m, off_h, off_m):
    global timer_on_h, timer_on_m, timer_off_h, timer_off_m
    timer_on_h  = on_h
    timer_on_m  = on_m
    timer_off_h = off_h
    timer_off_m = off_m
    print("Timer set ON={:02d}:{:02d} OFF={:02d}:{:02d}".format(on_h, on_m, off_h, off_m))

def stop_timer():
    kettle_pin.value(0)
    print("Timer stopped / SSR OFF")
    
def check_timer():
    if data_system.get("timer mode", 0) != 1:
        return
    d = _read_dt()
    sh, sm = data_system.get("start_time", [0, 0])
    eh, em = data_system.get("stop_time",  [0, 0])
    cur = d["hour"] * 60 + d["min"]
    on  = sh * 60 + sm
    off = eh * 60 + em
    if on < off:
        should_on = on <= cur < off
    else:
        should_on = cur >= on or cur < off
    if should_on and kettle_pin.value() == 0:
        kettle_pin.value(1)
    elif not should_on and kettle_pin.value() == 1:
        kettle_pin.value(0)
 
def fn_set_control_mode():
    global command, data_system
    print("fn_set_control_mode command:", command)
    mode = int(command[1])
    data_system["timer mode"] = mode

    if mode == 0:
        data_system["start_time"] = [0, 0]
        data_system["stop_time"]  = [0, 0]
        stop_timer()
        write_json()
        command = "16,0,0,0,0,0"
        display_result()
        command = "7,{}".format(kettle_pin.value())

    elif mode == 1:
        sh = int(command[2]); sm = int(command[3])
        eh = int(command[4]); em = int(command[5])
        data_system["start_time"] = [sh, sm]
        data_system["stop_time"]  = [eh, em]
        write_json()
        start_timer(sh,sm,eh,em)
        command = "16,1,{},{},{},{}".format(sh, sm, eh, em)
        
def input_control_mode():
    global command
    lcd.clear()
    lcd.putstr("Control Mode")
    lcd.move_to(0, 1)
    lcd.putstr("0=Manual 1=Timer")
    lcd.move_to(0, 2)
    lcd.putstr("Select:")
    mode = read_num()
    command = ["16", str(mode)]
    
    if mode == 0:
        # ── ไปหน้า 7 ทันที ──
        str_name = ["Kettle Control", "Select[0=OFF,1=ON]:"]
        input_data(7, str_name)
    
    elif mode == 1:
        # ── ON Time ──
        lcd.clear()
        lcd.putstr("==Timer ON Time==")
        lcd.move_to(0, 1)
        lcd.putstr("Hour(0-23): ")
        on_h = read_num()
        lcd.move_to(12, 1)
        lcd.putstr("{:02d}".format(on_h))
        lcd.move_to(0, 2)
        lcd.putstr("Min (0-59): ")
        on_m = read_num()
        lcd.move_to(12, 2)
        lcd.putstr("{:02d}".format(on_m))
        lcd.move_to(0, 3)
        lcd.putstr("ON ={:02d}:{:02d}  #=Next".format(on_h, on_m))
        wait_keypress()

        # ── OFF Time ──
        lcd.clear()
        lcd.putstr("==Timer OFF Time=")
        lcd.move_to(0, 1)
        lcd.putstr("Hour(0-23): ")
        off_h = read_num()
        lcd.move_to(12, 1)
        lcd.putstr("{:02d}".format(off_h))
        lcd.move_to(0, 2)
        lcd.putstr("Min (0-59): ")
        off_m = read_num()
        lcd.move_to(12, 2)
        lcd.putstr("{:02d}".format(off_m))
        lcd.move_to(0, 3)
        lcd.putstr("OFF={:02d}:{:02d}  #=OK".format(off_h, off_m))
        wait_keypress()

        command = ["16", "1", str(on_h), str(on_m), str(off_h), str(off_m)]

    
def handle_keypad1():
    global command, sta_comm
    
    deadline = time.ticks_add(time.ticks_ms(), 1000)
    key = None
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        key = scanKeypad()
        if key is not None:
            print("got key:", key)  
            break
        time.sleep_ms(20)
    print("keypad key:", key)
    if key is None:
        return

    if key == '*':
        print("keypad: * pressed")  # ← เพิ่ม
        lcd.clear()
        lcd.move_to(0,1)
        lcd.putstr("#=OK")
        lcd.move_to(12, 3)
        lcd.putstr("*=Exit")
        lcd.move_to(0, 0)
        lcd.putstr("Select 1-27:")
        ch = read_num()
        print("keypad: ch =", ch)
        
        #if 1 <= ch <= 27:
        if ch > 0 and ch <= 27 and ch != 5:
            if ch == 2:                
                str_name = ["Set Date", "Year:", "Month:", "Day:"]
                input_data(ch, str_name)                

            elif ch == 3:
                str_name = ["Set Time", "Hour:", "Minute:", "Second:"]
                input_data(ch, str_name)                
                
            elif ch == 6:
                str_name = ["WiFi Control", "Select[0-1]:", "", "#=OK"]
                input_data(ch, str_name)               

            elif ch == 7:
                str_name = ["Kettle Control", "Select[0=OFF,1=ON]:"]
                input_data(ch, str_name)
            elif ch == 10:
                str_name = ["Kettle Weight", "Put empty kettle", "then press #=OK"]
                lcd.clear()
                lcd.putstr(str_name[0])
                lcd.move_to(0, 1)
                lcd.putstr(str_name[1])
                lcd.move_to(0, 2)
                lcd.putstr(str_name[2])
                wait_keypress()
                command = ["10"]
            elif ch == 16: input_control_mode()
            elif ch == 18: pass
            elif ch == 20: pass
            elif ch == 21: pass            
            elif ch == 23: pass
            elif ch == 24: pass
            elif ch == 25: pass            
            elif ch == 27: pass
            else :
                command = [str(ch)]
            sta_comm = 1 # สั่งการทำงานผ่านคีย์แพด   

def input_data(ch, str_name):
    global command
    
    lcd.clear()
    lcd.putstr(str_name[0])
    
    command = [str(ch)]
    for y in range(	1, len(str_name)):
        lcd.move_to(0, y)
        lcd.putstr(str_name[y])
        d = read_num()
        command.append(str(d))     

def operation_comm():
    global command 
    
    if   command[0] == "1": fn_get_datetime()
    elif command[0] == "2": fn_set_date()
    elif command[0] == "3": fn_set_time()
    elif command[0] == "4": fn_get_wifi_info()
    elif command[0] == "5": pass
    elif command[0] == "6": fn_wifi_control()
    elif command[0] == "7": fn_kettle_control()
    elif command[0] == "8": fn_get_kettle_status()
    elif command[0] == "9": fn_set_zero(	)
    elif command[0] == "10": fn_set_kettle_weight()
    elif command[0] == "11": fn_get_weight()
    elif command[0] == "12": fn_get_current_water()
    elif command[0] == "13": fn_set_before_water()
    elif command[0] == "14": fn_get_before_water()
    elif command[0] == "15": fn_get_energy()
    elif command[0] == "16": fn_set_control_mode()     
    elif command[0] == "17": pass
    elif command[0] == "18": pass
    elif command[0] == "19": pass
    elif command[0] == "20": pass
    elif command[0] == "21": pass
    elif command[0] == "22": pass
    elif command[0] == "23": pass
    elif command[0] == "24": pass
    elif command[0] == "25": pass
    elif command[0] == "26": pass
    elif command[0] == "27": pass
    else: print("ไม่รู้จักคำสั่ง:", command[0])
    
def display_result():
    global command
    command1 = command.split(",")  
    ch = command1[0]
    #print(command)
    
    if   ch == "1":
        #command = f"1,{d['year']},{d['mon']},{d['day']},0,{d['hour']},{d['min']},{d['sec']}"
        str_date = "Date:{:04d}/{:02d}/{:02d}".format(int(command1[1]), int(command1[2]), int(command1[3]))        
        str_time = "Time:{:02d}:{:02d}:{:02d}    ".format(int(command1[5]), int(command1[6]), int(command1[7]))
        str_display = ["Datetime", str_date, str_time]
        display_lcd(str_display)
    elif ch == "2":
        str_display = ["Set Date", command1[1]]			#command = f"2,OK!"
        display_lcd(str_display)
    elif ch == "3":
        str_display = ["Set Time", command1[1]]			#command = f"3,OK!"
        display_lcd(str_display)
    elif ch == "4":
        
        str_display = [
            "WiFi info", 
            f"SSID:{command1[1]}", 
            f"KEY:{command1[2]}"
        ]
        display_lcd(str_display)    
    elif ch == "6":
        #command = f"6,0" or command = f"6,1"
        status_wifi = ["Disconnect", "Connected"]
        str_display = ["Connecting...", status_wifi[int(command1[1])]]
        display_lcd(str_display)
    elif ch == "7":
        status_kettle = ["Kettle: OFF", "Kettle: ON"]
        str_display = ["Kettle Control", status_kettle[int(command1[1])]]
        display_lcd(str_display)
    elif ch == "8":
        status_kettle = ["Kettle: OFF", "Kettle: ON "]
        str_display = ["Kettle Status", status_kettle[int(command1[1])]]
        display_lcd(str_display)        
    elif ch == "9":
        str_display = ["Set Zero","Weight:{:.1f}g".format(float(command1[1]))]
        display_lcd(str_display)
    elif ch == "10":
        str_display = [
            "Kettle Weight",
            "Saved!"
        ]
        display_lcd(str_display)

    elif ch == "11":
        str_display = [
            "Kettle Weight",
            "Weight:{:.1f}kg".format(float(command1[1])),

        ]
        display_lcd(str_display)
        
    elif ch == "12":
        str_display = [
            "Current Water",
            "Water:{:.1f}L".format(float(command1[1])),
        ]
        display_lcd(str_display)
    elif ch == "13":
        str_display = [
            "Saved!",
        ]
        display_lcd(str_display)
        
    elif ch == "14":
        str_display = [
            "Before Water",
            "Water:{:.2f}L".format(float(command1[1])),

        ]
        display_lcd(str_display)
    elif ch == "15":
        # หน้า 1
        str_display = [
            "V:{:>6}V  F:{:>4}Hz".format(command1[1], command1[5]),
            "I:{:>7}A  PF:{:>3}".format(command1[2], command1[6]),
            "P:{:>7}W".format(command1[3]),
            "Next..."
        ]
        display_lcd(str_display)
        
        # หน้า 2
        str_display = [
            "Energy",
            "E:{:>7}Wh".format(command1[4]),
            "Bill:{:>7} Baht".format(command1[7]),
        ]
        display_lcd(str_display)       
    elif ch == "16":
        mode = int(command1[1])
        if mode == 0:
            str_display = ["Control Mode", "Mode: Manual"]
        elif mode == 1:
            str_display = [
                "Control Mode: Timer",
                "ON :{:02d}:{:02d}".format(int(command1[2]), int(command1[3])),
                "OFF:{:02d}:{:02d}".format(int(command1[4]), int(command1[5])),
            ]
        display_lcd(str_display)
            
    elif ch == "17": pass
    elif ch == "18": pass
    elif ch == "19": pass
    elif ch == "20": pass
    elif ch == "21": pass
    elif ch == "22": pass
    elif ch == "23": pass
    elif ch == "24": pass
    elif ch == "25": pass
    elif ch == "26": pass
    elif ch == "27": pass   

def display_lcd(str_display):
    global sta_comm
    lcd.clear()     
    for y in range(	0, len(str_display)):
        lcd.move_to(0, y)
        lcd.putstr(str_display[y])
    if sta_comm == 1:
        lcd.move_to(0, 3)
        lcd.putstr("[Any Key]")
        wait_keypress()    

def write_json():
    global data_system
        
    # Write the data to JSON file        
    with open("data_system.json", "w") as outfile:
        json.dump(data_system, outfile)
    outfile.close()

def read_json():
    global data_system
    #Opening JSON file
    with open('data_system.json', 'r') as openfile: 
        #Reading the data from json file
        data_system = json.load(openfile)
    openfile.close()

# ============================================================
# ลูปหลัก
# ============================================================
rtc._OSF_reset()

delay_lcd = 500
delay_fb = 2000

last_lcd = 0
last_fb = 0
last_reconnect = 0
RECONNECT_INTERVAL = 10000

read_json()
if data_system['connect_status'] == 1:
    connect_wifi(data_system['ssid'], data_system['password'])
    show_status()
    last_reconnect = time.ticks_ms()
  
while True:
    new_time = time.ticks_ms()
    print("wifi:", wlan.isconnected(), "time:", new_time) 
    
    if (new_time - last_lcd) > delay_lcd:
        last_lcd = new_time
        show_status()                           
    
    sta_comm = 0 
    command = ""    
    
    handle_keypad1()#เรียก Fn_keypad
    
    
    if sta_comm == 1:
        operation_comm()
        display_result()           
    
    command = ""
    sta_comm = 0
    
    
    if data_system['connect_status'] == 1:
        if not wlan.isconnected():
            new_time2 = time.ticks_ms()
            if time.ticks_diff(new_time2, last_reconnect) > RECONNECT_INTERVAL:
                last_reconnect = new_time2
                connect_wifi(data_system['ssid'], data_system['password'])
                command = ""
                sta_comm = 0
                last_lcd = 0
                show_status()
    
        if wlan.isconnected():
            new_time1 = time.ticks_ms()
            if (new_time1 - last_fb) > delay_fb:
                last_fb = new_time1
                fb_get_start("comm", "var1")  # ← ยิง thread แล้ววิ่งต่อเลย
        
#                 firebase.get("comm", "var1", bg=0)
#                 command_app = firebase.var1                
                
            if fb_done and fb_result and fb_result != "0" and fb_result[0] != '0':
                print("->", fb_result)
                sta_comm = 2
                command = fb_result.split(",")
                fb_done = False
                firebase.put("comm", "0")
                if sta_comm == 2:
                    operation_comm()
                    firebase.put("esp", command)
                    time.sleep(2)
        
    if(data_system['timer mode'] != 0):
        check_timer() 
    
    if(data_system['record_status'] != 0):
        pass        
    

    

