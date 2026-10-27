# DDA cho Bubble Shooter 3: code C# tích hợp vào game

Sau mỗi lượt chơi, game tính 40 feature và model cho điểm rủi ro bỏ game. Từ điểm này, game quyết định số bóng của lượt kế tiếp.

- Không cần thư viện ngoài, chạy được với mọi bản Unity.
- Code là C# 5 thuần, không phụ thuộc Unity.

## File

| File | Việc làm |
|---|---|
| `DdaEngine.cs` | **Lớp duy nhất game gọi tới.** Ghi nhận sự kiện, cho biết số bóng của màn, xử lý sau mỗi lượt |
| `DdaPackage.cs` | Đọc gói model (4 file) và kiểm tra sha256; tra bảng màn, tier quốc gia, ngưỡng, tham số policy |
| `DdaModel.cs` | Đọc `model_trees.bin` và tính điểm `p` |
| `DdaFeatures.cs` | Tính 40 feature, công thức giống code train phía server |
| `DdaPolicy.cs` | Logic thêm/bớt bóng v6 |
| `DdaState.cs` | Dữ liệu lưu trên máy theo từng người chơi (lịch sử lượt, bộ đếm, trạng thái policy) |
| `DdaJson.cs` | Đọc/ghi JSON. Không dùng được `JsonUtility` vì nó không đọc được dictionary |

Gói model do server phát hành hằng ngày gồm 4 file:
- `model_trees.bin` (bản nén để tải về: `model_trees.bin.gz`)
- `model_manifest.json`
- `model_levels.json`
- `model_country_tier.json`

## Tích hợp

### 1. Khởi tạo (khi mở app)

```csharp
var pkg = DdaPackage.Load(
    File.ReadAllBytes(dir + "/model_trees.bin"),
    File.ReadAllBytes(dir + "/model_manifest.json"),
    File.ReadAllBytes(dir + "/model_levels.json"),
    File.ReadAllBytes(dir + "/model_country_tier.json"));       // sai sha256 -> ném lỗi

var state = DdaState.FromJson(PlayerPrefs.GetString("dda_state", ""));
var mode = isTreatment ? DdaMode.On : DdaMode.Off;             // nhóm A/B
dda = new DdaEngine(pkg, state, mode);
dda.SetCountry(countryName);                                   // tên quốc gia tiếng Anh, xem mục Lưu ý
dda.OnAppForeground(DateTime.UtcNow);
```

| Mode | Dùng cho | Gọi model | Đổi số bóng | Gửi tracking |
|---|---|---|---|---|
| `Off` | Nhóm đối chứng | Không | Không | Không |
| `Shadow` | Chạy ngầm 1-2 tuần để so khớp với server | Có | Không | Có |
| `On` | Nhóm treatment | Có | Có | Có |

Ở mọi mode vẫn gọi đủ các hàm bên dưới, để lịch sử người chơi luôn đúng nếu sau này bật DDA.

### 2. Vòng đời app

```csharp
void OnApplicationPause(bool paused)
{
    if (paused) { dda.OnAppBackground(DateTime.UtcNow); Save(); }
    else dda.OnAppForeground(DateTime.UtcNow);
}
```

Engine tự đếm phiên chơi: quay lại sau ít nhất 30 phút thì tính phiên mới, giống Firebase. Engine cũng tự đếm thời gian app ở foreground.

### 3. Vào màn

```csharp
int balls = dda.GetBallsForLevel(level);   // số bóng khởi đầu của lượt này (kể cả chơi lại)
```

- `On`: trả số bóng đã điều chỉnh nếu `level` đúng là màn kế tiếp đã tính sẵn. Màn kế tiếp là màn sau nếu vừa thắng, chính màn đó nếu vừa thua. Người chơi chọn màn khác thì trả số bóng gốc.
- `Off` / `Shadow`: luôn trả số bóng gốc trong `model_levels.json`.

Bóng nhận thêm trong màn (xem quảng cáo, booster) **không** cộng vào đây.

### 4. Trong lượt

```csharp
dda.OnAdImpression(valueMicros);   // mỗi quảng cáo có doanh thu, mọi loại (= event paid_ad_impression)
dda.OnScreenView();                // mỗi lần gửi screen_view
dda.OnRateDialog();                // mỗi lần hiện hộp thoại đánh giá (= rate_dialog_ev)
```

`valueMicros` là doanh thu tính theo micro USD:
- AdMob: `AdValue.Value`.
- MAX: `revenue * 1e6`.

### 5. Kết thúc lượt (đúng lúc gửi `level_up`)

```csharp
var res = dda.OnAttemptEnd(new DdaAttempt {
    Level = level,            // số màn thật, có thể > 1000
    Win = win,
    Stars = stars,            // thua = 0
    Remain = remain,          // số bóng dư thật
    SpecUsed = specUsed,      // số bóng đặc biệt đã dùng
    UserDo = userDo,          // nút bấm ở màn kết quả: 1 Next, 2 Home, 3 Replay
}, DateTime.UtcNow);

if (res.Track)
    foreach (var kv in res.TrackingParams()) levelUpParams[kv.Key] = kv.Value;   // gắn vào chính event level_up
SendLevelUp(levelUpParams);
Save();

void Save() { PlayerPrefs.SetString("dda_state", dda.State.ToJson()); }
```

- Chỉ gọi khi lượt có kết quả thắng hoặc thua, mỗi lượt đúng 1 lần. Bỏ dở giữa chừng thì không gọi.
- Truyền số bóng dư thật. Engine tự quy về số bóng gốc nếu lượt đó đã được thêm/bớt bóng.

Tracking gắn vào `level_up`:

| Param | Kiểu | Ý nghĩa |
|---|---|---|
| `dda_model_version` | string | Version gói model, vd `1.14` |
| `dda_p_value` | float | Điểm rủi ro sau lượt này |
| `balls_base` | int | Số bóng gốc của màn vừa chơi |
| `balls_delta` | int | Số bóng đã cấp trừ số bóng gốc (0 = không đổi) |
| `dda_action` | string | `add` / `keep` / `cut` |

`res` còn có `P`, `Flagged`, `LowRisk`, `NextLevel`, `NextBalls`, `Features` để debug.

### 6. Cập nhật gói model

Tải 4 file mới rồi gọi `DdaPackage.Load(...)`:
- Thành công thì gọi `dda.SetPackage(newPkg)`. Lịch sử người chơi giữ nguyên.
- Lỗi thì giữ gói cũ. Lỗi xảy ra khi sai sha256, hoặc gói có feature mà code chưa hỗ trợ (version MAJOR mới, cần cập nhật app).

Không hard-code ngưỡng hay tham số: model train lại hằng ngày, mọi thứ đọc từ `model_manifest.json`.

## Lưu ý

- **User cài app trước khi có DDA** không có lịch sử trên máy, nên số lượt, màn cao nhất, ngày từ lúc cài đều bị tính sai. Chỉ đưa vào A/B user cài mới từ bản app có DDA; user cũ để `Off`.
- **Tên quốc gia**:
  - `model_country_tier.json` dùng tên tiếng Anh như GA4, ví dụ `Japan`, `Vietnam`, `South Korea`, `Côte d’Ivoire`, `Congo - Kinshasa`.
  - Không tìm thấy thì tính là nhóm Z.
  - GA4 xác định quốc gia theo IP. Nguồn quốc gia trên máy (IP hay vùng của thiết bị) cần chốt với bên data.
- **Thời gian chơi**: engine đo thời gian app ở foreground, còn server tính từ `engagement_time` của Firebase. Hai cách đo có thể lệch nhẹ; sẽ đối chiếu trong giai đoạn `Shadow`.
- Mọi mốc thời gian dùng `DateTime.UtcNow`.

## Đã kiểm tra

Chạy 24,435 lượt giả lập (400 người chơi) qua `DdaEngine` ở mode `On`. Trạng thái được lưu rồi đọc lại sau mỗi sự kiện. Kết quả so với code server:

- 40 feature khớp `core/fe_lib.py`. Chênh lệch lớn nhất 1e-6, do bảng màn làm tròn 6 chữ số.
- Điểm `p` khớp LightGBM, chênh lệch tối đa 3e-8.
- Số bóng và trạng thái policy khớp `dda_policy_v6.py` ở 24,435/24,435 lượt.
- Biên dịch được với `-langversion:5`, không có cảnh báo.
