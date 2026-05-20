from datetime import datetime
import os

def save_to_file(content, output_dir="data", prefix="data"):
    try:
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/{prefix}_{timestamp}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Saved: {filename}")
        return filename

    except Exception as e:
        print(f"Error saving file: {e}")
        return ""
