try:
    from PIL import Image
    print("Pillow OK")
except Exception as e:
    print(f"Pillow missing: {e}")
