import requests
import time

BASE_URL = "http://localhost:5000/led"
MAX_BIN = 60  # всего ячеек

# пример цветов и режимов
colors = [1, 2, 3]    # красный, зеленый, белый
modes = [0, 1, 2]     # 0 - постоянный, 1 - моргание, 2 - другой

for color in colors:
    for mode in modes:
        print(f"Setting all bins to color={color}, mode={mode}")
        for bin_no in range(1, MAX_BIN + 1):
            payload = {"color": color, "mode": mode, "duration": 0}
            try:
                r = requests.post(f"{BASE_URL}/{bin_no}", json=payload, timeout=1)
                if r.ok:
                    print(f"Bin {bin_no} set successfully")
                else:
                    print(f"Bin {bin_no} failed: {r.status_code} {r.text}")
            except Exception as e:
                print(f"Bin {bin_no} error: {e}")
        # пауза между сменами режима/цвета
        time.sleep(1)