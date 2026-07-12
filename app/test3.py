import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load các biến từ file .env
load_dotenv()

# Lấy giá trị từ biến môi trường
api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

def main():
    if not api_key:
        print("Lỗi: Không tìm thấy API KEY trong file .env")
        return

    try:
        # Cấu hình Gemini
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # Gửi request
        response = model.generate_content("Chào bạn, hãy viết một câu chào ngắn gọn!")
        print(f"Gemini phản hồi: {response.text}")
        
    except Exception as e:
        print(f"Đã xảy ra lỗi: {e}")

if __name__ == "__main__":
    main()