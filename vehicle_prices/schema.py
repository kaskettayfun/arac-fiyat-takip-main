from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PriceRecord:
    Kayit_Tarihi: datetime
    Liste_Tarihi: date | None
    Marka: str
    Model: str
    Versiyon_Paket: str
    Model_Yili: int | None
    Yakit_Tipi: str
    Sanziman: str
    Motor_Hacmi_CC: int | None
    Motor_Gucu_BG: str
    Liste_Fiyati_TL: int
    Kampanyali_Fiyat_TL: int | None
    Para_Birimi: str
    Kaynak_URL: str
    Veri_Durumu: str
    Aciklama: str

    @classmethod
    def columns(cls) -> list[str]:
        return [field.name for field in fields(cls)]

    def as_row(self) -> list[Any]:
        values = asdict(self)
        return [values[column] for column in self.columns()]

    def dedupe_key(self) -> tuple[Any, ...]:
        return (
            self.Liste_Tarihi,
            self.Marka.casefold(),
            self.Model.casefold(),
            self.Versiyon_Paket.casefold(),
            self.Model_Yili,
        )

    def validate(self) -> None:
        if not self.Marka.strip() or not self.Model.strip():
            raise ValueError("Marka ve model zorunludur")
        if self.Model.strip().casefold() in {"-", "—", "n/a", "null", "none"}:
            raise ValueError("Model alanı boş yer tutucu olamaz")
        if self.Liste_Fiyati_TL <= 0:
            raise ValueError("Liste fiyatı pozitif bir tam sayı olmalıdır")
        if self.Para_Birimi != "TL":
            raise ValueError("Bu sürümde para birimi TL olmalıdır")
        if self.Veri_Durumu != "OK":
            raise ValueError("Fiyat kayıtlarında Veri_Durumu OK olmalıdır")
