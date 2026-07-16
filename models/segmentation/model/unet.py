import torch
import torch.nn as nn
from torchvision.models import resnet34

class ConvBlock(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(ConvBlock, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )
    
    def forward(self, x):
        return self.conv(x)

class ResNet34UNet(nn.Module):
    def __init__(self, out_classes=1):
        super(ResNet34UNet, self).__init__()
        
        resnet = resnet34(weights=None)
        
        self.encoder_stem = nn.Sequential(
            resnet.conv1,
            resnet.bn1
        )
        self.relu = resnet.relu
        self.maxpool = resnet.maxpool
        
        self.encoder_layer1 = resnet.layer1
        self.encoder_layer2 = resnet.layer2
        self.encoder_layer3 = resnet.layer3
        
        self.bottleneck = resnet.layer4
        
        self.up1 = nn.ConvTranspose2d(512, 512, kernel_size=2, stride=2)
        self.dec1 = ConvBlock(768, 256)
        
        self.up2 = nn.ConvTranspose2d(256, 256, kernel_size=2, stride=2)
        self.dec2 = ConvBlock(384, 128)
        
        self.up3 = nn.ConvTranspose2d(128, 128, kernel_size=2, stride=2)
        self.dec3 = ConvBlock(192, 64)
        
        self.up4 = nn.ConvTranspose2d(64, 64, kernel_size=2, stride=2)
        self.dec4 = ConvBlock(128, 64)
        
        self.up_final = nn.ConvTranspose2d(64, 32, kernel_size=2, stride=2)
        self.dec_final = ConvBlock(32, 32)
        
        self.out_conv = nn.Conv2d(32, out_classes, kernel_size=1)
    
    def forward(self, x):
        x0 = self.encoder_stem(x)
        x0 = self.relu(x0)
        
        x1 = self.maxpool(x0)
        x1 = self.encoder_layer1(x1)
        
        x2 = self.encoder_layer2(x1)
        x3 = self.encoder_layer3(x2)
        x4 = self.bottleneck(x3)
        
        d1 = self.up1(x4)
        d1 = torch.cat([d1, x3], dim=1)
        d1 = self.dec1(d1)
        
        d2 = self.up2(d1)
        d2 = torch.cat([d2, x2], dim=1)
        d2 = self.dec2(d2)
        
        d3 = self.up3(d2)
        d3 = torch.cat([d3, x1], dim=1)
        d3 = self.dec3(d3)
        
        d4 = self.up4(d3)
        d4 = torch.cat([d4, x0], dim=1)
        d4 = self.dec4(d4)
        
        d_final = self.up_final(d4)
        d_final = self.dec_final(d_final)
        
        out = self.out_conv(d_final)
        return torch.sigmoid(out)
