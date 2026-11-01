# Instagram Following Tracker CLI

Công cụ dòng lệnh viết bằng Python để ghi nhận danh sách **Following** trên Instagram, lưu lịch sử kiểm tra và so sánh thay đổi giữa các lần thu thập dữ liệu.

Ứng dụng chạy trực tiếp trong Terminal, sử dụng SQLite để lưu trữ cục bộ và cung cấp menu tương tác. Không cần trình duyệt hoặc máy chủ web.

> [!IMPORTANT]
> Dự án sử dụng [`instagrapi`](https://github.com/subzeroid/instagrapi), một thư viện **không chính thức**. Khả năng truy xuất dữ liệu phụ thuộc vào quyền xem của tài khoản đăng nhập và các giới hạn của Instagram. Chỉ sử dụng với dữ liệu mà bạn có quyền truy cập.

## Tính năng

- Thu thập danh sách Following thông qua API có phân trang.
- Lưu mỗi lần kiểm tra thành một bản ghi (snapshot) có thời gian, trạng thái và danh sách tài khoản.
- Xem lịch sử, chi tiết từng snapshot và toàn bộ username đã thu thập.
- So sánh hai snapshot, phát hiện tài khoản xuất hiện thêm hoặc không còn xuất hiện; nhận biết đổi username khi có ID ổn định.
- Phân biệt dữ liệu **đã xác minh đủ số lượng** với dữ liệu **chưa đầy đủ**, tránh đưa ra kết luận chắc chắn từ kết quả thiếu.
- Xuất dữ liệu ra JSON, TXT và CSV; tự động sao lưu từng lần kiểm tra.
- Quản lý phiên đăng nhập cục bộ, đổi tài khoản mục tiêu và thử phương pháp truy xuất dự phòng.
- Xóa **một** lần kiểm tra theo ID, có xác nhận trước khi thực hiện.

## Yêu cầu hệ thống

- Linux (ưu tiên Ubuntu hoặc các bản phân phối tương thích).
- Python **3.11 trở lên** và `python3-venv`.
- Kết nối Internet để kiểm tra dữ liệu mới.
- Tài khoản Instagram hợp lệ có quyền xem danh sách cần kiểm tra.

## Cài đặt

Sao chép mã nguồn từ repository GitHub vào máy:

```bash
git clone <REPOSITORY_URL>
cd instagram-following-tracker
```

> Thay `<REPOSITORY_URL>` bằng URL HTTPS hoặc SSH của repository. Nếu tải mã nguồn dưới dạng ZIP, hãy giải nén rồi mở Terminal trong thư mục chứa `ig_following.py`.

Cài đặt môi trường Python:

```bash
sudo apt update
sudo apt install -y python3 python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Khởi chạy:

```bash
chmod +x run.sh
./run.sh
```

Những lần sử dụng tiếp theo chỉ cần chạy `./run.sh` từ thư mục dự án. Không cần cài lại thư viện nếu môi trường `.venv` vẫn còn.

## Hướng dẫn sử dụng

Chương trình cung cấp các lựa chọn sau:

| Menu | Chức năng |
| --- | --- |
| `1` | Kiểm tra danh sách Following |
| `2` | Xem lịch sử các lần kiểm tra |
| `3` | Xem chi tiết và toàn bộ username của một lần kiểm tra |
| `4` | So sánh hai lần kiểm tra theo ID |
| `5` | Xuất toàn bộ lịch sử ra JSON và CSV |
| `6` | Nhập dữ liệu từ ứng dụng web cũ (nếu có) |
| `7` | Đăng nhập hoặc làm mới phiên Instagram |
| `8` | Thay đổi username tài khoản mục tiêu |
| `9` | Thử phương pháp truy xuất dự phòng |
| `10` | Xóa một lần kiểm tra theo ID |
| `0` | Thoát chương trình |

**Thiết lập lần đầu:** Chọn `8` để đặt tài khoản mục tiêu, sau đó chọn `1` để bắt đầu kiểm tra. Khi được yêu cầu, đăng nhập bằng tài khoản Instagram của chính bạn. Mật khẩu được nhập ẩn trong Terminal; ứng dụng không lưu mật khẩu dưới dạng văn bản thuần.

**Xóa lịch sử:** Menu `10` chỉ xóa một snapshot theo ID sau khi xác nhận. Các bản ghi khác và phiên đăng nhập được giữ nguyên. File xuất tổng hợp được tạo trước đó không tự động cập nhật theo thao tác xóa.

## Trạng thái dữ liệu và cách diễn giải

| Trạng thái | Ý nghĩa |
| --- | --- |
| `verified` | Phân trang kết thúc không lỗi, số tài khoản duy nhất khớp số lượng Instagram trả về và có ID cần thiết. |
| `partial` | Danh sách thu thập chưa đầy đủ hoặc chưa đáp ứng điều kiện xác minh. |
| `legacy` | Dữ liệu nhập từ nguồn cũ, chỉ dùng để tham khảo. |
| `failed` | Lượt kiểm tra không hoàn thành do lỗi. |

Chương trình chỉ tự động xác nhận thay đổi giữa **hai snapshot `verified` tương thích của cùng tài khoản mục tiêu**. Nếu một trong hai snapshot chưa đầy đủ, các chênh lệch chỉ có giá trị tham khảo; username vắng mặt **không chứng minh** tài khoản đó đã bị unfollow.

Thời điểm ghi nhận snapshot là **thời điểm phát hiện thay đổi**, không phải thời điểm chính xác người dùng thực hiện thao tác Follow hoặc Unfollow. Thứ tự danh sách trả về từ API cũng không thể coi là thứ tự Follow theo thời gian.

Trạng thái `verified` chỉ xác nhận kết quả đáp ứng các điều kiện kiểm tra của ứng dụng, không bảo đảm tuyệt đối rằng dữ liệu do Instagram cung cấp luôn chính xác.

## Lưu trữ dữ liệu

Dữ liệu được lưu cục bộ trong thư mục `data/` (được tạo khi chạy):

```text
instagram-following-tracker/
├── ig_following.py
├── run.sh
├── requirements.txt
├── README.md
├── tests/
└── data/                     # Dữ liệu cục bộ; không đưa lên Git
    ├── config.json           # Cấu hình tài khoản
    ├── instagram_session.json # Phiên đăng nhập nhạy cảm
    ├── history.sqlite3       # Cơ sở dữ liệu lịch sử
    └── backups/              # JSON, TXT, CSV xuất và sao lưu
```

Mỗi lần kiểm tra tạo bản sao lưu JSON và TXT tương ứng. Có thể xuất CSV từ màn hình chi tiết hoặc xuất lịch sử tổng hợp từ menu `5`.

Để sao lưu dữ liệu sang máy khác, hãy thoát chương trình rồi sao chép thư mục `data/` qua kênh an toàn. Không công khai thư mục này hoặc file phiên đăng nhập.

## Bảo mật và quyền riêng tư

- **Không commit** `data/`, `.venv/`, file session, cookie, token, bản xuất Following hoặc bản sao lưu cá nhân lên GitHub.
- Kiểm tra `git status` và `git diff --cached --name-only` trước khi commit.
- Không chia sẻ file `data/instagram_session.json` hoặc thông tin xác thực.
- Nếu Instagram yêu cầu CAPTCHA, checkpoint hoặc báo giới hạn truy cập, hãy dừng thử lại liên tục và xử lý yêu cầu xác minh qua ứng dụng/trang Instagram chính thức.
- Dự án không phải sản phẩm chính thức của Instagram hoặc Meta.

## Kiểm thử

Chạy các bài kiểm thử có trong dự án:

```bash
python3 -m unittest discover -s tests -v
```

Các bài kiểm thử cục bộ không thay thế cho việc kiểm tra khả năng truy cập API Instagram trong môi trường thực tế.

## Giới hạn

- API không chính thức có thể thay đổi, bị giới hạn tốc độ hoặc không trả về đầy đủ dữ liệu.
- Không thể xác định chính xác thời điểm hoặc thứ tự Follow từ danh sách thu thập.
- Kết quả phụ thuộc vào quyền truy cập và trạng thái phiên đăng nhập.
- Công cụ không thực hiện Follow hoặc Unfollow tài khoản.

## Tài liệu tham khảo

- [instagrapi — GitHub](https://github.com/subzeroid/instagrapi)
- [instagrapi — Usage Guide](https://subzeroid.github.io/instagrapi/latest/usage-guide/user/)

---

**Lưu ý:** Dự án phục vụ mục đích quản lý dữ liệu và học tập. Người sử dụng chịu trách nhiệm tuân thủ quy định của Instagram và pháp luật áp dụng.
