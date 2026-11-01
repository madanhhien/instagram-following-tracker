#!/usr/bin/env bash
# Dọn duy nhất các artifact cũ đã được tạo trong dự án thử nghiệm Instagram.
# Chuyển vào Trash, KHÔNG dùng rm -rf hoặc sudo; KHÔNG chạm vào dữ liệu CLI.
set -euo pipefail
[[ -n "${HOME:-}" && "$HOME" != '/' ]] || { echo 'HOME không hợp lệ. Đã hủy.' >&2; exit 1; }

# Không động đến Instagram archive cá nhân, ảnh chụp, profile Brave hoặc CLI hiện hành.
legacy_names=(
  instagram_follow_tracker.html
  instagram_follow_tracker_v2.html
  instagram_follow_tracker_v3.html
  instagram_follow_tracker_v4.html
  instagram_lay_following.js
  instagram_following_tracker_ubuntu.zip
  instagram_following_tracker_ubuntu_v2.zip
  instagram_following_tracker_ubuntu_brave.zip
  instagram_following_tracker_brave_fix.zip
  instagram_following_tracker_brave_fix_v2.zip
  instagram_following_tracker_network_test.zip
  instagram_following_tracker_network_diagnostic_v2.zip
  instagram_following_tracker_strict_diagnostic_v3.zip
  instagram_following_cli.zip
  instagram_following_cli_v2.zip
  instagram_following_cli_v3.zip
)
report_names=(
  instagram_network_diagnostic.json
  'instagram_network_diagnostic (1).json'
  instagram_following_backup_2026-11-01.json
  instagram_following_2026-11-01.txt
)
file_paths=()
report_paths=()
for root in "$HOME/Downloads" "$HOME"; do
  for filename in "${legacy_names[@]}"; do
    file="$root/$filename"
    [[ -f "$file" || -L "$file" ]] && file_paths+=("$file")
  done
  for filename in "${report_names[@]}"; do
    file="$root/$filename"
    [[ -f "$file" || -L "$file" ]] && report_paths+=("$file")
  done
done

web_dirs=()
for dir in "$HOME/ig_tracker_ubuntu" "$HOME/Downloads/ig_tracker_ubuntu"; do
  # Only accept recognizable legacy app dirs. Never trash a different folder with the same name.
  if [[ -d "$dir" && -f "$dir/app.py" && -f "$dir/seed_2026-11-01.json" ]]; then
    web_dirs+=("$dir")
  elif [[ -e "$dir" ]]; then
    echo "⚠ Không xác nhận được cấu trúc app web cũ, sẽ BỎ QUA: $dir"
  fi
done

backup_dirs=()
for dir in \
  "$HOME/ig_tracker_brave_extension_backup" \
  "$HOME/ig_tracker_backup_before_v3" \
  "$HOME/ig_tracker_backup_data_20261101"; do
  [[ -d "$dir" || -L "$dir" ]] && backup_dirs+=("$dir")
done

show_group() {
  local title="$1"; shift
  printf '\n%s (%s đường dẫn):\n' "$title" "$#"
  if (( $# == 0 )); then echo '  (Không có)'; return; fi
  printf '  %s\n' "$@"
}
show_group '1. File HTML/JS và ZIP thử nghiệm không dùng nữa' "${file_paths[@]}"
show_group '2. Thư mục app WEB cũ + .venv + extension + dữ liệu WEB cũ' "${web_dirs[@]}"
show_group '3. Báo cáo JSON/TXT chẩn đoán cũ (mặc định GIỮ)' "${report_paths[@]}"
show_group '4. Thư mục backup app WEB cũ (mặc định GIỮ)' "${backup_dirs[@]}"
cat <<'NOTE'

KHÔNG ĐỤNG TỚI:
  ~/ig_following_cli/ (bao gồm .venv, data, history.sqlite3, session, backups)
  ~/ig_following_cli_data_backup* (bản backup CLI quan trọng)
  ZIP CLI V4 hiện tại, ảnh gốc, các file xuất dữ liệu Instagram cá nhân
  profile trình duyệt Brave/Chrome và các ứng dụng khác
Cần gỡ tiện ích Following Tracker trong brave://extensions > Remove trước.
Chưa có tệp nào bị xóa. Nếu thực hiện sẽ CHUYỂN VÀO THÙNG RÁC, có thể phục hồi.
NOTE

if [[ "${1:-}" == '--preview' || $# == 0 ]]; then
  echo 'Để dọn các mục trên: ./cleanup_old_artifacts.sh --apply'
  exit 0
fi
if [[ "${1:-}" != '--apply' || $# -ne 1 ]]; then
  echo 'Cú pháp: ./cleanup_old_artifacts.sh [--preview|--apply]' >&2
  exit 2
fi
command -v gio >/dev/null 2>&1 || { echo 'Thiếu lệnh gio (Trash). Chưa thay đổi gì. Không dùng rm -rf thay thế.' >&2; exit 1; }

read -r -p 'Gõ đúng DON APP WEB CU để cho phép dọn các nhóm trên: ' allow
[[ "$allow" == 'DON APP WEB CU' ]] || { echo 'Đã hủy, không thay đổi gì.'; exit 0; }

trash_group() {
  local heading="$1";shift
  local path answer
  if (( $# == 0 )); then return; fi
  read -r -p "$heading? (y/N): " answer
  if [[ "$answer" != 'y' ]]; then echo 'Đã giữ nhóm này.'; return; fi
  for path in "$@"; do
    [[ -e "$path" || -L "$path" ]] || continue
    if gio trash "$path"; then
      printf '✓ Đã chuyển vào Thùng rác: %s\n' "$path"
    else
      printf '⚠ Không chuyển được: %s (hãy kiểm tra thủ công)\n' "$path" >&2
    fi
  done
}

trash_group '1. Chuyển HTML/JS/ZIP cũ vào Thùng rác' "${file_paths[@]}"
trash_group '2. Chuyển TOÀN BỘ thư mục APP WEB cũ vào Thùng rác (kể cả .venv và data web)' "${web_dirs[@]}"
trash_group '3. Chuyển báo cáo chẩn đoán JSON/TXT vào Thùng rác (không bắt buộc)' "${report_paths[@]}"
trash_group '4. Chuyển backup APP WEB cũ vào Thùng rác (không bắt buộc)' "${backup_dirs[@]}"
echo 'Đã hoàn thành phần dọn dẹp được chọn. Thùng rác có thể dùng để phục hồi.'
echo 'Lịch sử CLI vẫn ở ~/ig_following_cli/data/.'
