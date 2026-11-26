"""Neural depth models; PyTorch is optional for the rest of ApexHFT."""

from __future__ import annotations

import torch
from torch import nn


class DeepLOB(nn.Module):
    """DeepLOB-style width reduction, temporal inception, and LSTM."""

    def __init__(self, levels: int) -> None:
        super().__init__()
        self.book = nn.Sequential(
            nn.Conv2d(1, 32, (1, 2), stride=(1, 2)), nn.LeakyReLU(0.01),
            nn.Conv2d(32, 32, (3, 1), padding=(1, 0)), nn.LeakyReLU(0.01),
            nn.Conv2d(32, 32, (1, 2), stride=(1, 2)), nn.LeakyReLU(0.01),
            nn.Conv2d(32, 32, (3, 1), padding=(1, 0)), nn.LeakyReLU(0.01),
            nn.Conv2d(32, 32, (1, levels)), nn.LeakyReLU(0.01),
        )
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv2d(32, 32, 1), nn.LeakyReLU(0.01),
                          nn.Conv2d(32, 32, (k, 1), padding=(k // 2, 0)), nn.LeakyReLU(0.01))
            for k in (3, 5)
        ] + [
            nn.Sequential(nn.MaxPool2d((3, 1), stride=1, padding=(1, 0)),
                          nn.Conv2d(32, 32, 1), nn.LeakyReLU(0.01))
        ])
        self.timeline = nn.LSTM(96, 64, batch_first=True)
        self.head = nn.Linear(64, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        depth = self.book(x.unsqueeze(1))
        merged = torch.cat([branch(depth) for branch in self.branches], dim=1)
        timeline, _ = self.timeline(merged.squeeze(-1).transpose(1, 2))
        return self.head(timeline[:, -1])


class TemporalCNNLSTM(nn.Module):
    def __init__(self, levels: int) -> None:
        super().__init__()
        self.conv = nn.Conv1d(4 * levels, 48, kernel_size=3, padding=1)
        self.timeline = nn.LSTM(48, 48, batch_first=True)
        self.head = nn.Linear(48, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        timeline, _ = self.timeline(self.conv(x.transpose(1, 2)).relu().transpose(1, 2))
        return self.head(timeline[:, -1])


class DepthTransformer(nn.Module):
    def __init__(self, levels: int, lookback: int) -> None:
        super().__init__()
        self.embed = nn.Linear(4 * levels, 48)
        self.positions = nn.Parameter(torch.zeros(1, lookback, 48))
        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(48, 4, dim_feedforward=96, dropout=0.1, batch_first=True),
            num_layers=2,
        )
        self.head = nn.Linear(48, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # The encoder only sees the already-observed input window.
        hidden = self.encoder(self.embed(x) + self.positions)
        return self.head(hidden[:, -1])


MODEL_NAMES = ("deeplob", "cnn-lstm", "transformer")


def make_depth_model(name: str, levels: int, lookback: int) -> nn.Module:
    if name == "deeplob":
        return DeepLOB(levels)
    if name == "cnn-lstm":
        return TemporalCNNLSTM(levels)
    if name == "transformer":
        return DepthTransformer(levels, lookback)
    raise ValueError(f"unknown depth model: {name}")
