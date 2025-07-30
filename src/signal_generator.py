# -----------------------------------------------------------------------------
#  Project: CANinoApp
#  Author: Nicasio Canino <nicasio.canino@phd.unipi.it>
#  Organization: Department of Information Engineering (DII), University of Pisa
#  Collaborators: Sergio Saponara <sergio.saponara@unipi.it>, Daniele Rossi <daniele.rossi1@unipi.it>
#  Copyright 2025 Nicasio Canino
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -----------------------------------------------------------------------------

import math
from typing import Any


class SignalGenerator:
    def __init__(self, signal: Any):
        self.signal = signal
        # default: costante = 0
        self.mode = "constant"  # 'sin', 'list', etc.
        self.parameters: dict[str, float] = {}

    def get_value(self, t: float) -> float:
        # esempio: valore costante
        if self.mode == "constant":
            return self.parameters.get("value", 0)
        if self.mode == "sin":
            amp = self.parameters.get("amplitude", 1)
            freq = self.parameters.get("frequency", 1)
            return amp * math.sin(2 * math.pi * freq * t)
        # TODO: implementare 'list' e altri
        return 0
