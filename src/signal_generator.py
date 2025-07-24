import math
from typing import Any

class SignalGenerator:
    def __init__(self, signal: Any):
        self.signal = signal
        # default: costante = 0
        self.mode = 'constant'  # 'sin', 'list', etc.
        self.parameters: dict[str, float] = {}

    def get_value(self, t: float) -> float:
        # esempio: valore costante
        if self.mode == 'constant':
            return self.parameters.get('value', 0)
        if self.mode == 'sin':
            amp = self.parameters.get('amplitude', 1)
            freq = self.parameters.get('frequency', 1)
            return amp * math.sin(2 * math.pi * freq * t)
        # TODO: implementare 'list' e altri
        return 0