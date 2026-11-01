# Instagram Following Tracker — Terminal (Ubuntu)

Ứng dụng Python có menu. **Không cần Playwright, không cần cuộn Brave, không cần mở HTML.** Sử dụng thư viện **instagrapi**, là API **không chính thức**. Không có đảm bảo Instagram sẽ trả về đủ danh sách hoặc luôn cho đăng nhập. Sử dụng cho danh sách Following mà tài khoản của bạn được phép xem.

## 1. Cài đặt trên Ubuntu 25.10

Giải nén vào thư mục home, giữ nguyên app cũ:

```bash
cd ~
unzip -o ~/Downloads/instagram_following_cli.zip
cd ~/ig_following_cli
sudo apt install -y python3 python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

Nếu bạn đã giải nén từ GUI vào thư mục khác, hãy `cd` đến đúng thư mục `ig_following_cli`.

**Không cần cài lại Chromium/Playwright.** Dùng `python3` phiên bản 3.11 trở lên. Script không cần `sudo` khi chạy.

## 2. Cách dùng menu

- **1**: Kiểm tra Following (mặc định tài khoản `yu_hjeiiun.n`). Khi lần đầu cần đăng nhập, hãy nhập **username và mật khẩu của chính bạn** trong Terminal. Đây là phiên riêng của thư viện instagrapi, không sử dụng cookie Brave. Không gửi mật khẩu cho người khác. Mật khẩu nhập ẩn và không ghi vào file.
- **2**: Xem lịch sử ngày giờ các lần kiểm tra. Cột `Follow mới` là `—` khi chưa đủ hai mốc có dữ liệu đáng tin cậy.
- **3**: Xem kết quả chi tiết lần kiểm tra theo ID, gồm username mới, số tài khoản, ngày giờ.
- **4**: So sánh hai lần kiểm tra bất kỳ. Nếu một lượt thiếu dữ liệu thì kết quả **chỉ là đối chiếu tham khảo**, không kết luận unfollow.
- **5**: Xuất toàn bộ lịch sử JSON và CSV, ngoài file sao lưu JSON tự tạo sau **mỗi lượt kiểm tra**.
- **6**: Nhập các bản ghi từ app web cũ `~/ig_tracker_ubuntu/data/tracker.sqlite3` (không sửa dữ liệu cũ), chống nhập trùng.
- **7**: Làm mới phiên đăng nhập.
- **8**: Đổi username tài khoản mục tiêu.
- **9**: Phương pháp lấy danh sách dự phòng của thư viện (khi API chính không đầy đủ). Không tự hợp nhất hai kết quả thiếu.
- **0**: Thoát.

## 3. Hiểu đúng kết quả

Script đọc các trang API và kiểm tra **hai điều kiện**: (1) phân trang đã kết thúc mà không có lỗi và (2) số username/ID duy nhất bằng `following_count` của tài khoản đích. Khi đủ thì đánh dấu `verified` (tức **khớp số lượng API và hết phân trang**), không phải đảm bảo tuyệt đối server Instagram đúng trong mọi tình huống.

Nếu kiểm tra ngày 01/11 được 147/147 đầy đủ, ngày 02/11 được 148/148 đầy đủ và ID tài khoản tương thích, chương trình sẽ lưu `new_follow_count=1`, username mới và ngày giờ của lượt kiểm tra thứ hai. **Đây là khoảng thời gian phát hiện**, không phải ngày/giờ chính xác người đó bấm Follow. Nếu có nhiều tài khoản mới, không thể xác định họ đã follow theo thứ tự nào.

Mốc ảnh cũ 01/11 (146/147 theo dữ liệu đã trích xuất) luôn là `legacy` — không dùng để tự động kết luận follow mới. Chương trình tự nhập lịch sử từ app cũ (nếu có) lần đầu và **không sửa** `~/ig_tracker_ubuntu/data/tracker.sqlite3`.

Nếu Instagram báo CAPTCHA, `challenge_required`, `429` hay từ chối đăng nhập: **dừng**, không đăng nhập liên tục để cố vượt kiểm tra. Mở Instagram trên Brave/điện thoại và xác minh tài khoản theo hướng dẫn của Instagram. Phiên của thư viện có thể bị chặn ngay cả khi Brave vẫn đăng nhập bình thường.

## 4. Lưu trữ

- `data/history.sqlite3`: cơ sở dữ liệu các lượt kiểm tra.
- `data/backups/YYYYMMDD..._check_ID.json`: sao lưu **tự động từng lần** (bao gồm username mới, ngày kiểm tra, tổng Following, trạng thái).
- `data/backups/*_ALL_HISTORY.json`, `*_SUMMARY.csv`: sao lưu toàn bộ theo yêu cầu menu 5.
- `data/instagram_session.json`: phiên Instagram có chứa token/cookie nhạy cảm, quyền file chỉ user đọc. **Không gửi file này cho ai, không đưa vào GitHub**.
- `data/config.json`: chỉ chứa username đăng nhập và username mục tiêu, **không có mật khẩu**.

Để sao lưu sang máy khác, đóng chương trình rồi copy toàn bộ `data/`. Để xóa phiên đăng nhập mà giữ lịch sử, xóa riêng `data/instagram_session.json`. Không xóa `data/history.sqlite3`.

## 5. Chạy lần sau

```bash
cd ~/ig_following_cli
./run.sh
```

Nếu bạn gặp lỗi, gửi **tên lỗi và nội dung Terminal sau khi đã che thông tin cá nhân**. Không gửi mật khẩu, session file, cookie hoặc token.

## 6. Lưu ý giới hạn

Meta không công khai API hỗ trợ truy xuất toàn bộ Following của tài khoản khác. `instagrapi` là thư viện bên thứ ba; tài khoản có thể bị giới hạn hoặc challenge. Việc lấy danh sách 147/147 phải được xác nhận từ máy của bạn, chưa được kiểm thử với tài khoản thực trong quá trình xây dựng file này.

Tài liệu thư viện: https://subzeroid.github.io/instagrapi/latest/usage-guide/user/

## 7. Bổ sung — Xem TOÀN BỘ Following trong một lần kiểm tra

Tại menu chọn **3**, nhập ID lần kiểm tra, chẳng hạn **4**. Script sẽ tự in **toàn bộ 146 username đã thu thập** cùng ID Instagram (nếu có), không còn phải nhập `y` để hiện danh sách. Thứ tự hiển thị là thứ tự nhận dữ liệu từ API, **không phải thứ tự follow theo thời gian**.

Mỗi lần kiểm tra tự động tạo **hai bản sao lưu**: file JSON chứa thời gian, trạng thái, số follow mới và username mới được xác minh (nếu có); và file TXT chứa toàn bộ username của lượt đó. Trong menu 3, có thể xuất thêm CSV nếu muốn mở danh sách trong Excel/LibreOffice.

**Quan trọng với lượt #4:** 146/147 là bản ghi `partial`; danh sách 146 username là dữ liệu thực tế đã lấy được, nhưng không thể khẳng định 1 tài khoản chưa xuất hiện là unfollow. Lượt kiểm tra đủ số lượng đầu tiên tạo mốc đáng tin cậy; kể từ khi có **hai** bản ghi `verified` cùng tài khoản, script mới xác nhận follow mới bằng ID và lưu chúng trong lịch sử.

### Cập nhật từ bản cũ (không xóa lịch sử và phiên đăng nhập)

Dừng script ở menu bằng `0`, sao lưu dữ liệu, rồi giải nén gói nâng cấp vào thư mục home:

```bash
cp -a ~/ig_following_cli/data ~/ig_following_cli_data_backup
unzip -o ~/Downloads/instagram_following_cli_v2.zip -d ~
cd ~/ig_following_cli
./run.sh
```

Không cần đăng nhập lại nếu phiên Instagram đã lưu còn hiệu lực. Không xoá thư mục `data/`.

## 8. CLI V4 — Chỉ xóa một lượt kiểm tra

Chọn **10** trong menu, nhập một ID đã hiển thị ở menu 2, gõ `XOA <ID>` để xác nhận. **Không có lựa chọn xóa toàn bộ lịch sử**. Script chỉ xóa đúng một lượt thuộc tài khoản mục tiêu, đồng thời tính lại kết quả so sánh của các mốc đã xác minh còn lại. Mặc định giữ file sao lưu riêng, muốn xóa file đó thì gõ `y` khi được hỏi. File `ALL_HISTORY` xuất thủ công từ trước không bị tự động xóa, có thể còn chứa lượt đã xóa.

## 9. Dọn ứng dụng web cũ và các file thử nghiệm (KHÔNG ảnh hưởng CLI)

Trước hết hãy đóng máy chủ web cũ nếu còn chạy (`Ctrl+C` trong Terminal chạy `app.py`) và gỡ extension **Following Tracker - Local Bridge** tại `brave://extensions` → Remove. Các extension của trình duyệt không thể được gỡ bằng cách chỉ xóa folder mã nguồn.

Dọn các file thử nghiệm HTML/JS, các ZIP thử nghiệm trong Downloads và thư mục web `~/ig_tracker_ubuntu` (bao gồm `.venv`, `brave_extension`, dữ liệu web cũ) bằng script đi kèm. Script chỉ dùng **gio trash** (chuyển vào Thùng rác), không xóa vĩnh viễn. Xem trước:

```bash
cd ~/ig_following_cli
./cleanup_old_artifacts.sh
```

Sau khi đọc danh sách và xác nhận các tệp thuộc bản cũ, chạy:

```bash
./cleanup_old_artifacts.sh --apply
```

Nó hỏi xác nhận riêng cho từng nhóm. Các file chẩn đoán JSON và bản backup web cũ được **giữ mặc định**, chỉ chuyển vào Thùng rác nếu bạn chủ động chọn. **Không đụng** `~/ig_following_cli`, `.venv`, `data`, `~/ig_following_cli_data_backup*`, ZIP V4 mới, ảnh chụp hay file Instagram export cá nhân.

## 10. Nâng cấp lên CLI V4

```bash
# Thoát CLI bằng menu 0 rồi sao lưu
cp -a ~/ig_following_cli/data ~/ig_following_cli_data_backup_before_v4
unzip -o ~/Downloads/instagram_following_cli_v4.zip -d ~
cd ~/ig_following_cli
./run.sh
```

Giữ phiên đăng nhập và lịch sử cũ. Không phải cài lại `instagrapi`.
