# 📢 Facebook Group Auto Poster (GUI + CLI)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Engine-Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright" />
  <img src="https://img.shields.io/badge/UI-Tkinter-FFD43B?style=for-the-badge&logo=python&logoColor=black" alt="GUI" />
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows" />
</p>

Công cụ tự động đăng bài viết và video hàng loạt lên các Nhóm (Facebook Groups) hoặc Trang cá nhân qua **Playwright**, tích hợp giao diện **Tkinter GUI** hiện đại kèm chế độ dòng lệnh **CLI**.

---

## ✨ Tính năng chính

- 🖥️ **Giao diện người dùng đầy đủ (Tkinter GUI)**: Kéo-thả video/hình ảnh, chỉnh sửa nội dung bài viết trực quan.
- 🌐 **Tích hợp Profile Cốc Cốc / Chrome**: Sử dụng trực tiếp profile trình duyệt có sẵn để không cần đăng nhập lại tài khoản Facebook.
- 📋 **Quản lý hàng đợi bài đăng (Post Queue)**:
  - Hỗ trợ nhập/xuất danh sách nhóm từ file `.txt`.
  - Hẹn giờ đăng bài tự động (`Schedule`), đặt bước nhảy thời gian thông minh giữa các nhóm.
  - Tùy chỉnh quyền riêng tư (`Công khai`, `Bạn bè`, `Chỉ mình tôi`).
- 🤖 **Tự động hóa an toàn với Playwright**:
  - Tự động vượt các popup cảnh báo, điền caption và upload video.
  - Hỗ trợ chế độ chạy ẩn danh/không bật cửa sổ (`Headless mode`) và chế độ thử nghiệm không đăng thật (`Dry Run`).
- 📊 **Theo dõi trạng thái thời gian thực**: Log chi tiết tiến trình đăng, đếm ngược thời gian chờ giữa các bài viết để chống checkpoint/spam.

---

## 🚀 Hướng dẫn khởi chạy

### 1. Khởi động nhanh (Khuyên dùng)
Nhấp đúp chuột vào file:
```cmd
Start_FB_Tool.bat
```
*(Script sẽ tự động kiểm tra Python, khởi tạo môi trường `.venv`, cài đặt thư viện cần thiết và mở giao diện GUI).*

### 2. Cài đặt thủ công
```bash
# Tạo và kích hoạt môi trường ảo
python -m venv .venv
.\.venv\Scripts\activate

# Cài đặt thư viện và trình duyệt Chromium cho Playwright
pip install -r requirements.txt
python -m playwright install chromium

# Chạy giao diện GUI
python fb_group_poster_gui.py
```

### 3. Chạy qua dòng lệnh (CLI Mode)
Bạn có thể tự động hóa bằng file danh sách `.csv`:
```bash
python fb_group_poster.py --csv posts.csv
```
*(Tham khảo cấu trúc file mẫu tại `posts.sample.csv`).*

---

## 📖 Hướng dẫn sử dụng cơ bản

1. **Chọn Profile Trình duyệt**:
   - Tích chọn `Dùng profile thật` $	o$ chọn profile đã đăng nhập sẵn Facebook (Chrome hoặc Cốc Cốc) $	o$ bấm **Chẩn đoán** để kiểm tra kết nối.
2. **Nhập danh sách nhóm**:
   - Thêm từng link Group hoặc bấm **Import TXT** để tải danh sách hàng loạt.
3. **Soạn bài & Đặt lịch**:
   - Chọn media (kéo thả video/ảnh vào giao diện), nhập Caption bài viết và chọn thời gian đăng.
   - Bấm **Thêm tất cả nhóm** để đưa vào Hàng đợi (Queue).
4. **Bắt đầu đăng**:
   - Kiểm tra lại hàng đợi $	o$ bấm **Start** để tool tự động thực hiện.

---

## ⚠️ Lưu ý quan trọng
- *Chỉ sử dụng công cụ cho các tài khoản và nhóm bạn có quyền quản trị hoặc được phép đăng bài.*
- *Nên cài đặt khoảng cách thời gian giữa các bài đăng (`MIN_DELAY_SECONDS`, `MAX_DELAY_SECONDS`) hợp lý để tránh bị hạn chế tài khoản.*