import cv2
import numpy as np

IMAGE_PATH = "bolts.jpg"

# -------------------------
# НАСТРОЙКИ (крутить тут)
# -------------------------
# Порог белого фона в HSV:
# фон белый = V высокий, S низкий
S_MAX_BG = 60     # чем меньше, тем "белее" (50-80)
V_MIN_BG = 180    # чем больше, тем ярче (170-210)

# Морфология маски деталей
OPEN_K = 3        # убрать мелкий мусор
OPEN_IT = 1

CLOSE_K = 2       # подлечить дырки/резьбу (НЕ делай слишком большим!)
CLOSE_IT = 1

# Фильтр по площади (выкинуть мусорные компоненты)
MIN_AREA = 2000   # под твоё разрешение (для твоего фото обычно 1500-5000)

# Детектор "слипшихся" болтов:
# если компонент заметно больше типичного болта — делим watershed'ом
SPLIT_AREA_MULT = 1.6  # 1.4..2.0

DEBUG_SAVE = True

def save(name, img):
    if DEBUG_SAVE:
        cv2.imwrite(name, img)

# -------------------------
# 1) Загрузка
# -------------------------
img = cv2.imread(IMAGE_PATH)
if img is None:
    raise RuntimeError(f"Не удалось открыть {IMAGE_PATH}")

hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
H, S, V = cv2.split(hsv)

# -------------------------
# 2) Убираем белый фон (делаем маску деталей)
# -------------------------
# фон: S низкий и V высокий
bg_mask = ((S <= S_MAX_BG) & (V >= V_MIN_BG)).astype(np.uint8) * 255

# детали = НЕ фон
parts = cv2.bitwise_not(bg_mask)

# Лёгкая подчистка шумов на старте
k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (OPEN_K, OPEN_K))
k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CLOSE_K, CLOSE_K))

parts = cv2.morphologyEx(parts, cv2.MORPH_OPEN, k_open, iterations=OPEN_IT)
parts = cv2.morphologyEx(parts, cv2.MORPH_CLOSE, k_close, iterations=CLOSE_IT)

save("dbg_bg_mask.png", bg_mask)
save("dbg_parts_mask.png", parts)

# -------------------------
# 3) Находим связные компоненты (пятна)
# -------------------------
num, labels, stats, _ = cv2.connectedComponentsWithStats(parts, connectivity=8)

areas = stats[1:, cv2.CC_STAT_AREA]  # без фона
areas = areas[areas >= MIN_AREA]

if len(areas) == 0:
    print("0 компонентов после фильтра MIN_AREA. Уменьши MIN_AREA или подстрой S_MAX_BG/V_MIN_BG.")
    raise SystemExit(0)

median_area = float(np.median(areas))

# -------------------------
# 4) Счёт + деление “слипшихся” компонентов
# -------------------------
def split_component_with_watershed(component_mask: np.ndarray) -> int:
    """
    Делит 1 большое пятно на несколько (если внутри несколько болтов).
    Возвращает количество объектов, найденных внутри.
    """
    # Закрыть дырки ещё раз локально
    local = component_mask.copy()
    local = cv2.morphologyEx(local, cv2.MORPH_CLOSE, k_close, iterations=1)

    # Distance transform
    dist = cv2.distanceTransform(local, cv2.DIST_L2, 5)
    dist = cv2.GaussianBlur(dist, (9, 9), 0)

    # "семена" объектов — вершины distance map
    _, sure_fg = cv2.threshold(dist, 0.45 * dist.max(), 255, 0)
    sure_fg = sure_fg.astype(np.uint8)

    # фон
    sure_bg = cv2.dilate(local, k_open, iterations=2)
    unknown = cv2.subtract(sure_bg, sure_fg)

    # маркеры
    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0

    # watershed требует 3-канальную картинку
    dummy = cv2.cvtColor(local, cv2.COLOR_GRAY2BGR)
    markers = cv2.watershed(dummy, markers)

    # labels > 1 — это объекты
    obj_labels = np.unique(markers)
    obj_labels = obj_labels[obj_labels > 1]
    return int(len(obj_labels))

count = 0
vis = img.copy()

for i in range(1, num):
    area = stats[i, cv2.CC_STAT_AREA]
    if area < MIN_AREA:
        continue

    x, y, w, h = (stats[i, cv2.CC_STAT_LEFT],
                  stats[i, cv2.CC_STAT_TOP],
                  stats[i, cv2.CC_STAT_WIDTH],
                  stats[i, cv2.CC_STAT_HEIGHT])

    # Маска конкретной компоненты
    comp = (labels == i).astype(np.uint8) * 255

    # Если пятно слишком большое, вероятно там 2 болта (или больше) -> делим локально
    if area > SPLIT_AREA_MULT * median_area:
        n_inside = split_component_with_watershed(comp)
        count += max(1, n_inside)
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 165, 255), 2)  # оранжевый: делили
    else:
        count += 1
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)    # красный: обычный

print("Количество болтов:", count)
print(f"median_area={median_area:.0f}, split_if_area>{SPLIT_AREA_MULT:.2f}*median")

save("dbg_result.png", vis)

cv2.imshow("parts mask", parts)
cv2.imshow("result", vis)
cv2.waitKey(0)
cv2.destroyAllWindows()
