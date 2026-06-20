"""Dump a binary P6 PPM to a crude ASCII rendering for quick inspection."""

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
    # Downscale to fit terminal.
    cols = 80
    rows = 40
    x_step = max(1, w // cols)
    y_step = max(1, h // rows)
    out = []
    for y in range(0, h, y_step):
        line = []
        for x in range(0, w, x_step):
            i = (y * w + x) * 3
            r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
            # xterm background is dark, text light.
            brightness = (r + g + b) / 3
            if brightness > 180:
                line.append("#")
            elif brightness > 100:
                line.append(".")
            else:
                line.append(" ")
        out.append("".join(line).rstrip())
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
