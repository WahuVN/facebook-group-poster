# FB Group Video Poster (GUI + CLI)

Tool Python nhẹ để tự đăng video vào các nhóm Facebook từ danh sách bạn chuẩn bị sẵn.

## 1) Mở nhanh (khuyên dùng)

- Double click file: `Start_FB_Tool.bat`
- Script này sẽ tự tạo `.venv`, cài package, rồi mở GUI.

## 2) Chạy bản giao diện bằng lệnh

```bash
python fb_group_poster_gui.py
```

## 3) Dùng Cốc Cốc profile A1 (đã tích hợp)

Trong GUI, ngay phần **Cấu hình chạy**:

1. Tick `Dùng Cốc Cốc profile thật`
2. `Cốc Cốc exe`: để mặc định hoặc trỏ tới:
   - `C:\Program Files\CocCoc\Browser\Application\browser.exe`
3. `User Data`: để mặc định:
   - `C:\Users\<user>\AppData\Local\CocCoc\Browser\User Data`
4. Bấm `Quét profile`
5. Bấm `Chọn nhanh A1` (hoặc chọn tay `A1 (Profile 4)` nếu có)
6. Bấm `Start`

> Nếu báo lỗi profile bị khóa (`locked`), hãy tắt hết cửa sổ Cốc Cốc rồi chạy lại.

## 4) Luồng dùng GUI

1. **Danh sách nhóm**: thêm `group_url` (hoặc import từ file `.txt`, mỗi dòng 1 link).
2. **Soạn bài**:
   - Chọn media (video/hình) hoặc kéo-thả trực tiếp vào cửa sổ
   - Nhập giờ đăng (ví dụ `2026-05-05 21:30`) hoặc để trống để đăng ngay
   - Chọn quyền riêng tư: `Mặc định` / `Công khai` / `Bạn bè` / `Chỉ mình tôi`
   - Nhập caption
3. Bấm:
   - `Thêm nhóm chọn`, hoặc
   - `Thêm tất cả nhóm`
4. Kiểm tra hàng đợi, rồi bấm `Start`.
5. Khi cần dừng thì bấm `Stop`.

### Tính năng GUI

- Quản lý nhiều nhóm và nhiều bài trong hàng đợi
- Nhúng sẵn 4 nhóm WW: bấm `Nạp 4 nhóm WW`
- Đăng trang cá nhân nhanh: bấm `Thêm trang cá nhân` (đích `https://www.facebook.com/me`)
- Tùy chỉnh quyền riêng tư khi đích là trang cá nhân (Công khai/Bạn bè/Chỉ mình tôi)
- Quản lý nhóm nhanh: `Cập nhật nhóm chọn`, `Mở nhóm`, `Import TXT`, `Export TXT`
- Kéo-thả vào cửa sổ: nhận media ngay, và hỗ trợ import nhóm từ `.txt`
- Nút giờ nhanh: `Now`, `+5m`, `+15m`, `+30m`, `+60m`
- Xếp lịch theo nhóm: chọn `Bước lịch (phút)` rồi bấm `Xếp lịch theo nhóm chọn`
- Double click dòng queue để nạp lại editor và sửa nhanh
- `Cập nhật dòng chọn` + `Nhân đôi dòng`
- Chọn nhiều nhóm nhanh: `Chọn tất cả` / `Bỏ chọn`
- Áp dụng hàng loạt: `Áp dụng giờ cho dòng chọn`, `Áp dụng giờ cho tất cả`, `Áp dụng nhóm chọn`, `Áp dụng media cho dòng chọn`
- Áp dụng hàng loạt quyền riêng tư cho các dòng đã chọn trong queue
- Nút `Chẩn đoán` kiểm tra nhanh profile/video/path
- Lưu/Nạp plan (`.json`)
- `Dry Run` để thử dữ liệu mà không đăng thật
- `Headless` để chạy ẩn trình duyệt
- Log realtime và trạng thái chờ đếm ngược

## 5) Nếu vẫn chưa mở được tool

1. Chạy bằng `Start_FB_Tool.bat` (không chạy bằng click vào `.py`).
2. Tắt toàn bộ Cốc Cốc rồi mở lại tool.
3. Trong GUI bấm `Chẩn đoán` để xem mục nào lỗi.
4. Nếu lỗi Python, cài lại Python 3.11+ và tick `Add Python to PATH` khi cài.
5. Nếu lỗi profile, kiểm tra:
   - `Cốc Cốc exe`: `C:\Program Files\CocCoc\Browser\Application\browser.exe`
   - `User Data`: `C:\Users\<user>\AppData\Local\CocCoc\Browser\User Data`
   - Profile: `A1 (Profile 4)`

## 6) Cài đặt thủ công (nếu không dùng BAT)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## 7) Chạy bản CLI (tuỳ chọn)

```bash
python fb_group_poster.py --csv posts.csv
```

- Dùng `posts.sample.csv` làm mẫu để tạo `posts.csv`.
- Cột CSV: `enabled,group_url,video_path,caption,schedule_at,audience`.
- `audience` là tùy chọn: `default` / `public` / `friends` / `only_me` (chủ yếu dùng cho trang cá nhân).

## 8) Cấu hình ENV (tuỳ chọn)

Copy `.env.example` thành `.env` rồi chỉnh nếu cần:

- `HEADLESS`
- `FB_SESSION_PATH`
- `FB_LOCALE`
- `FB_TIMEZONE`
- `SLOW_MO_MS`
- `POST_TIMEOUT_MS`
- `MIN_DELAY_SECONDS`
- `MAX_DELAY_SECONDS`
- `BROWSER_EXECUTABLE_PATH`
- `BROWSER_USER_DATA_DIR`
- `BROWSER_PROFILE_DIRECTORY`

## 9) Lưu ý quan trọng

- Chỉ dùng cho tài khoản/nhóm bạn có quyền đăng bài.
- Giao diện Facebook có thể đổi; khi đó cần cập nhật selector.
- Đăng quá dày có thể bị giới hạn tính năng tài khoản.
