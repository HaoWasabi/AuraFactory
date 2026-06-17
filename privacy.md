# Chính Sách Bảo Mật (Privacy Policy) - AuraFactory

Chính sách bảo mật này mô tả cách thức **AuraFactory** ("Hệ thống") thu thập, xử lý và bảo vệ dữ liệu khi vận hành các cấu phần Agentic AI nhằm tự động hóa thiết lập hạ tầng trên máy chủ Discord của bạn. Chúng tôi cam kết bảo vệ dữ liệu và không gian số của người dùng theo các tiêu chuẩn an toàn cao nhất.

## 1. Dữ Liệu Thu Thập và Phạm Vi Tiếp Cận
Để thực hiện các tác vụ tự động hóa hạ tầng, AuraFactory cần tiếp cận và xử lý các thông tin sau từ Discord API:
* **Thông tin định danh cấu trúc:** ID Máy chủ (Guild ID), ID Kênh (Channel ID), ID Vai trò (Role ID) để thiết lập sơ đồ hạ tầng cấu trúc.
* **Metadata của máy chủ:** Tên kênh, tên vai trò và sơ đồ phân quyền hiện tại nhằm mục đích phân tích và tối ưu hóa không gian số bằng AI.
* **Dữ liệu tương tác (Lệnh/Nhắc lệnh):** Nội dung các câu lệnh cấu hình, cấu trúc prompt hoặc các tương tác qua Slash Command được gửi tới hệ thống để AI hiểu và thực thi tác vụ.

> 🔒 **Nguyên tắc An toàn:** AuraFactory **KHÔNG** thu thập, ghi âm hoặc lưu trữ nội dung tin nhắn trò chuyện thông thường, thông tin cá nhân nhạy cảm, hoặc lịch sử hoạt động riêng tư của các thành viên trong máy chủ. Dữ liệu văn bản chỉ được xử lý tạm thời (runtime) để phục vụ cho luồng tư duy của mô hình AI (Agent Reasoning).

## 2. Mục Đích Sử Dụng Dữ Liệu
Dữ liệu thu thập được sử dụng duy nhất cho các mục đích:
* Vận hành lõi xử lý Agentic AI để tự động hóa việc thiết lập hạ tầng (chia kênh, phân quyền).
* Lưu trữ trạng thái cấu hình (Configuration State) để phục vụ tính năng phục hồi (rollback) hoặc nâng cấp hạ tầng khi Quản trị viên yêu cầu.
* Giám sát hiệu năng và cải thiện độ chính xác cho mô hình AI của đồ án.

## 3. Chia Sẻ và Lưu Trữ Dữ Liệu
* **Bên thứ ba:** Chúng tôi **KHÔNG** chia sẻ, bán hoặc chuyển giao dữ liệu máy chủ của bạn cho bất kỳ bên thứ ba nào ngoại trừ các API mô hình ngôn ngữ lớn (LLM Providers) được tích hợp trong hệ thống (với cam kết bảo mật dữ liệu đầu vào và không sử dụng dữ liệu này để huấn luyện mô hình công cộng).
* **Thời gian lưu trữ:** Dữ liệu cấu hình hạ tầng sẽ được lưu trữ an toàn trong cơ sở dữ liệu của hệ thống cho đến khi ứng dụng bị gỡ bỏ khỏi máy chủ hoặc có yêu cầu xóa từ Quản trị viên.

## 4. Quyền Kiểm Soát Dữ Liệu của Quản Trị Viên
Bạn giữ toàn quyền kiểm soát dữ liệu của máy chủ mình thông qua các hành động:
* **Thu hồi quyền:** Bạn có thể trục xuất (Kick/Ban) AuraFactory khỏi máy chủ bất kỳ lúc nào để chấm dứt ngay lập tức mọi quyền truy cập hạ tầng.
* **Yêu cầu xóa dữ liệu:** Sử dụng lệnh hệ thống (nếu có) hoặc liên hệ trực tiếp với đội ngũ phát triển qua Server hỗ trợ để yêu cầu xóa toàn bộ lịch sử cấu hình hạ tầng đã lưu trong cơ sở dữ liệu.

## 5. Liên Hệ Đội Ngũ Phát Triển
Nếu bạn có bất kỳ câu hỏi nào về cách các Agent AI xử lý dữ liệu máy chủ, vui lòng liên hệ:
* **Discord Support Server:** [Đường link server hỗ trợ của AuraFactory]