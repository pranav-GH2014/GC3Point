from dataclasses import dataclass

@dataclass
class TransactionCharges:
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    sebi_charges: float
    stamp_duty: float
    total_charges: float

class ZerodhaOptionChargesCalculator:
    """
    Computes exact statutory and broker charges for NSE Options trades per current SEBI/Zerodha tariff:
    - Brokerage: ₹20 per executed order or 0.03% (whichever is lower) -> ₹20 flat per leg
    - STT/CTT: 0.1% on SELL side premium turnover (effective Oct 2024 revised STT rate for options sale)
    - Exchange Transaction Charges: 0.03553% on premium turnover (NSE options revised)
    - GST: 18% on (Brokerage + Exchange Charges + SEBI Charges)
    - SEBI Turnover Charges: ₹10 per crore (0.0001%) on premium turnover
    - Stamp Duty: 0.003% on BUY side premium turnover
    """

    @classmethod
    def calculate(cls, buy_price: float, sell_price: float, quantity: int) -> TransactionCharges:
        buy_turnover = buy_price * quantity
        sell_turnover = sell_price * quantity

        # 1. Brokerage: ₹20 per leg flat
        brokerage = 20.0 + (20.0 if sell_price > 0 else 0.0)

        # 2. STT: 0.1% on sell leg premium turnover
        stt = round(sell_turnover * 0.001, 2)

        # 3. Exchange transaction charges: 0.03553% on total premium turnover
        exchange_charges = round((buy_turnover + sell_turnover) * 0.0003553, 2)

        # 4. Stamp duty: 0.003% on buy leg premium turnover
        stamp_duty = round(buy_turnover * 0.00003, 2)

        # 5. SEBI turnover fee: 0.0001% on total premium turnover
        sebi_charges = round((buy_turnover + sell_turnover) * 0.000001, 2)

        # 6. GST: 18% on (Brokerage + Exchange charges + SEBI charges)
        gst = round((brokerage + exchange_charges + sebi_charges) * 0.18, 2)

        total_charges = round(brokerage + stt + exchange_charges + stamp_duty + sebi_charges + gst, 2)

        return TransactionCharges(
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            gst=gst,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            total_charges=total_charges
        )
