# Instagram Following & Followers Tracker CLI

Công cụ dòng lệnh bằng Python để ghi nhận danh sách **Following** (tài khoản đang được theo dõi) và **Followers** (tài khoản đang theo dõi) trên Instagram, lưu lịch sử và so sánh thay đổi giữa các lần kiểm tra.

Ứng dụng chạy trong Terminal, lưu dữ liệu bằng SQLite trên máy cá nhân, không yêu cầu máy chủ web hoặc tiện ích trình duyệt.

> **Lưu ý:** Dự án sử dụng [`instagrapi`](https://github.com/subzeroid/instagrapi), một thư viện API **không chính thức**. Chức năng phụ thuộc vào quyền truy cập, phiên đăng nhập và giới hạn từ Instagram. Chỉ thu thập danh sách mà tài khoản đăng nhập được phép xem. Không có tính năng vượt qua quyền riêng tư hoặc tự động Follow/Unfollow.

## Nâng cấp V6 — Thu thập Followers chính xác hơn

V5 gọi trực tiếp `user_followers_v1_chunk()` để phân trang. Instagram đôi khi trả về một tập Followers bị giới hạn và **không trả cursor tiếp theo**. Đây là giới hạn từ phía Instagram, không thể giải quyết chỉ bằng cách gọi thêm trang cùng cursor. V6 chuyển menu `11` sang:

1. **Nguồn chính:** `instagrapi.Client.user_followers()`; API mức cao của thư viện hỗ trợ tự chuyển nguồn khi danh sách bị giới hạn.
2. **Dự phòng có điều kiện:** nếu nguồn chính thiếu, thử một lượt `user_followers_private_gql_chunk()` độc lập để tìm danh sách đầy đủ.
3. **Đối chiếu cuối lượt:** kiểm tra lại số lượng và ID tài khoản mục tiêu. Nếu thay đổi trong quá trình thu thập, đánh dấu `partial`.
4. **Không xác minh dữ liệu ghép:** nếu cả hai nguồn đều thiếu, chương trình có thể lưu *hợp* các ID đã thấy để xem lại, nhưng **không đánh dấu `verified` và không cho so sánh tự động**, kể cả khi tổng số ID ghép vừa bằng số Followers hiển thị.

**`verified` là tiêu chí kiểm tra của ứng dụng (danh sách một nguồn đầy đủ theo số đếm và số đếm ổn định), không phải bằng chứng chính xác tuyệt đối.** API không chính thức không thể bảo đảm 100% nếu Instagram ẩn, giới hạn, hay thay đổi danh sách trong lúc kiểm tra. Nếu tài khoản yêu cầu checkpoint/CAPTCHA/giới hạn, chương trình ngừng truy vấn dự phòng thay vì cố vượt qua giới hạn.

V6 tương thích database V5 và **không sửa lịch sử hiện có**. Các bản ghi cũ trạng thái `partial` vẫn giữ nguyên trạng thái.

## Tính năng

| Tính năng | Following | Followers |
| --- | :---: | :---: |
| Thu thập dữ liệu có phân trang, báo tiến độ | ✓ | ✓ (ưu tiên cơ chế tự dự phòng) |
| Lưu mỗi lần kiểm tra cùng thời gian và trạng thái | ✓ | ✓ |
| Xem lịch sử và toàn bộ username/ID của từng lượt | ✓ | ✓ |
| So sánh hai lượt theo ID | ✓ | ✓ |
| Nhận diện tài khoản thêm, bớt và đổi username | ✓ | ✓ |
| Xuất dữ liệu JSON, TXT và CSV | ✓ | ✓ |
| Thử phương thức API dự phòng | ✓ | ✓ |
| Xóa **một** lượt kiểm tra theo ID, có xác nhận | ✓ | ✓ |

Lịch sử Following và Followers được lưu **độc lập trong cùng một cơ sở dữ liệu**. So sánh chỉ áp dụng giữa hai lượt cùng loại danh sách và cùng tài khoản mục tiêu.

## Yêu cầu

- Linux (ví dụ Ubuntu), Python 3.11 trở lên và `python3-venv`.
- Kết nối Internet khi kiểm tra mới.
- Tài khoản Instagram có quyền truy cập danh sách cần kiểm tra.

## Cài đặt

Nếu sử dụng mã nguồn từ GitHub:

```bash
git clone <REPOSITORY_URL>
cd <THU_MUC_DU_AN>
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x run.sh
./run.sh
```

Thay `<REPOSITORY_URL>` và `<THU_MUC_DU_AN>` bằng địa chỉ và tên thư mục thực tế. Nếu thiếu module `venv` trên Ubuntu, cài `python3-venv` từ trình quản lý gói.

**Cách dùng những lần sau:** mở Terminal trong thư mục dự án và chạy `./run.sh`. Phiên đăng nhập có thể hết hạn và khi đó chương trình sẽ yêu cầu đăng nhập lại.

## Menu và cách sử dụng

| Menu | Following | Menu | Followers |
| :---: | --- | :---: | --- |
| `1` | Kiểm tra Following | `11` | Kiểm tra Followers (tự chọn nguồn dự phòng khi thiếu) |
| `2` | Lịch sử Following | `12` | Lịch sử Followers |
| `3` | Chi tiết và toàn bộ username | `13` | Chi tiết và toàn bộ username |
| `4` | So sánh hai lượt | `14` | So sánh hai lượt |
| `5` | Xuất lịch sử JSON/CSV | `15` | Xuất lịch sử JSON/CSV |
| `9` | API dự phòng | `16` | API dự phòng |
| `10` | Xóa **một** lượt theo ID | `17` | Xóa **một** lượt theo ID |

Các chức năng chung: `6` nhập dữ liệu ứng dụng cũ (Following), `7` đăng nhập/làm mới phiên, `8` chọn tài khoản mục tiêu, `0` thoát.

### Kiểm tra lần đầu

1. Chọn **`8`** và nhập username mục tiêu (không cần dấu `@`). Nếu đã có cấu hình từ phiên bản trước, chương trình vẫn giữ nguyên username đã chọn.
2. Chọn **`11`** để kiểm tra Followers hoặc **`1`** để kiểm tra Following.
3. Khi được hỏi, đăng nhập bằng tài khoản Instagram của chính bạn. Mật khẩu nhập ẩn; chương trình không cố ý lưu mật khẩu thuần văn bản.
4. Chương trình lấy dữ liệu qua API phù hợp, ghi nhận số lượng username duy nhất và so sánh với số lượng Instagram báo. Với Followers, nguồn chính tự quản lý phân trang nên số trang được ghi là `0` (không được API mức cao cung cấp), không có nghĩa là không truy vấn. Sau khi hoàn thành, bản ghi và file JSON/TXT được lưu cục bộ.
5. Chọn **`12`** hoặc **`2`** để xem lịch sử. Ghi nhớ ID của từng lượt kiểm tra.
6. Chọn **`13`** hoặc **`3`**, nhập ID để xem toàn bộ username đã thu được. Có thể xuất thêm CSV.
7. Sau **ít nhất hai lượt kiểm tra đủ điều kiện**, chọn **`14`** hoặc **`4`**, nhập hai ID (cũ trước, mới sau) để so sánh.

Ví dụ với Followers: nếu ở lượt trước có A, B và lượt sau có B, C thì chương trình ghi nhận **C xuất hiện thêm** và **A không còn xuất hiện**. Chỉ khi cả hai lượt đã xác minh đủ dữ liệu, chương trình mới coi đây là thay đổi được xác nhận theo tiêu chí nội bộ.

## Trạng thái dữ liệu

| Trạng thái | Ý nghĩa |
| --- | --- |
| `verified` | Phân trang kết thúc không lỗi, số lượng ID/username duy nhất khớp số lượng Instagram trả về và có Instagram ID. |
| `partial` | Thu thập thiếu, lỗi phân trang hoặc kết quả chưa đạt điều kiện xác minh. |
| `legacy` | Dữ liệu cũ được nhập để tham khảo, không dùng làm mốc xác nhận thay đổi. |
| `failed` | Lượt kiểm tra không hoàn thành do lỗi. |

**Cảnh báo quan trọng:** Nếu Instagram báo 200 Followers nhưng chỉ thu được 198, bản ghi là `partial`. Hai tài khoản không xuất hiện **không thể mặc nhiên coi là đã bỏ theo dõi**. Lượt `partial` không thay thế mốc `verified` để tự động xác nhận chênh lệch.

Thời gian bản ghi được lưu theo múi giờ `Asia/Ho_Chi_Minh` (UTC+07). Thứ tự trả về của API không mặc định là thứ tự theo thời gian Follow. Ngày giờ của một snapshot là **thời điểm kiểm tra/phát hiện**, không phải thời điểm chính xác một người bắt đầu hoặc ngừng theo dõi. `verified` không bảo đảm API Instagram chính xác tuyệt đối.

## Lưu trữ và bảo mật

```text
<THU_MUC_DU_AN>/
├── ig_following.py
├── run.sh
├── requirements.txt
├── README.md
├── tests/
└── data/                      # Dữ liệu cá nhân, không commit lên Git
    ├── config.json           # Tài khoản đăng nhập và mục tiêu
    ├── instagram_session.json # Phiên đăng nhập nhạy cảm
    ├── history.sqlite3       # Following + Followers (có phân loại)
    └── backups/              # JSON, TXT, CSV cho từng lượt
```

- Mỗi lượt kiểm tra tạo backup JSON và danh sách TXT; có thể xuất CSV theo lượt.
- Danh sách Following và Followers nằm trong hai nhóm lịch sử khác nhau nhưng dùng một database. ID lượt kiểm tra là duy nhất giữa cả hai nhóm.
- Không commit `data/`, `.venv/`, file session/cookie/token, dữ liệu seed hoặc các bản xuất cá nhân. Giữ `.gitignore` hiện có hoặc tham khảo file `.gitignore.example` trong bộ cài.
- Dừng chương trình trước khi sao lưu hoặc chuyển dữ liệu sang máy khác. Bảo quản thư mục `data/` qua kênh an toàn.
- Nếu Instagram yêu cầu CAPTCHA/checkpoint hoặc báo giới hạn, dừng thử lại liên tục; kiểm tra tài khoản bằng ứng dụng Instagram chính thức.

### Nâng cấp từ phiên bản chỉ có Following

Từ V5 chương trình có cơ chế **tự chuyển đổi cấu trúc SQLite** khi chạy lần đầu: các bản ghi cũ được nhận diện là `following`, các bản ghi Followers mới có `kind=followers`. Chương trình không xóa các bản ghi trước đây, không yêu cầu đăng nhập lại nếu phiên vẫn hợp lệ và vẫn giữ tài khoản mục tiêu từ `data/config.json`.

**Nên sao lưu toàn bộ thư mục `data/` trước khi cập nhật**, sau khi đã đóng CLI. Không xóa, không ghi đè thư mục `data/` khi cài bản mới.

Phiên bản mới không tích hợp dữ liệu thử nghiệm/username cá nhân vào mã nguồn. Với bản cài mới, hãy chọn tài khoản mục tiêu qua menu `8`.

## Kiểm thử

Chạy bộ kiểm thử offline:

```bash
python3 -m unittest discover -s tests -v
```

Các bài kiểm thử mô phỏng phân trang, kiểm tra lịch sử, so sánh, xóa từng lượt và chuyển đổi cơ sở dữ liệu. Chúng **không** thay thế kiểm thử thực tế trên phiên Instagram hợp lệ.

## Giới hạn kỹ thuật

- Instagram có thể thay đổi API, giới hạn tốc độ, yêu cầu xác minh hoặc không cho phép truy cập Followers của tài khoản riêng tư.
- Số lượng hiển thị trên trang cá nhân có thể thay đổi trong lúc phân trang; các lượt thiếu phải được đánh dấu `partial`.
- Chương trình có thể hợp nhất các ID thu được từ hai API trong *cùng một lần kiểm tra* để tham khảo, nhưng **không bao giờ dùng dữ liệu hợp nhất từ hai danh sách thiếu để tạo một lượt `verified`**. Các lượt kiểm tra khác nhau không được hợp nhất để xác minh.
- Mỗi lượt so sánh đối chiếu toàn bộ danh sách đã lưu; chương trình không biết thời điểm chính xác tài khoản Follow hoặc Unfollow.
- Công cụ chỉ đọc dữ liệu, không tự Follow/Unfollow, không vượt qua quyền truy cập tài khoản.

## Tài liệu tham khảo

- [instagrapi — mã nguồn](https://github.com/subzeroid/instagrapi)
- [instagrapi — API danh sách người dùng](https://subzeroid.github.io/instagrapi/latest/usage-guide/user/)

Dự án không liên kết chính thức với Instagram hoặc Meta. Người sử dụng có trách nhiệm tuân thủ các quy định áp dụng.
