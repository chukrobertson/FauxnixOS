"""Dump top-left region of a PPM to ASCII."""

import sys


def main(path):
    with open(path, "rb") as f:
        data = f.read()
    header_end = data.index(b"\n255\n") + 5
    header = data[:header_end].decode("ascii")
    parts = header.split()
    assert parts[0] == "P6", parts[0]
    w, h = int(parts[1]), int(parts[2])
    pixels = data[header_end:]
    region_h = min(120, h)
    region_w = min(200, w)
    for y in range(0, region_h, 2):
        line = []
        for x in range(region_w):
            i = (y * w + x) * 3
            r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
            # xterm black bg, green text
            if g > 150 and r < 100 and b < 100:
                line.append("#")
            elif r > 200 and g > 200 and b > 200:
                line.append(".")
            elif r < 80 and g < 80 and b < 80:
                line.append(" ")
            else:
                line.append("+")
        print("".join(line).rstrip())


if __name__ == "__main__":
    main(sys.argv[1])
