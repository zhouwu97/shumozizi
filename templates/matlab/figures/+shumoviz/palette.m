function colors = palette()
%PALETTE 返回适合白底印刷和常见色觉缺陷的 Okabe-Ito 配色。

colors = struct();
colors.blue = [0, 114, 178] / 255;
colors.orange = [230, 159, 0] / 255;
colors.green = [0, 158, 115] / 255;
colors.vermillion = [213, 94, 0] / 255;
colors.purple = [204, 121, 167] / 255;
colors.sky = [86, 180, 233] / 255;
colors.yellow = [240, 228, 66] / 255;
colors.black = [35, 35, 35] / 255;
colors.gray = [125, 125, 125] / 255;
colors.light_gray = [225, 228, 232] / 255;

anchors = [ ...
    247, 251, 255; ...
    198, 219, 239; ...
    107, 174, 214; ...
    33, 113, 181; ...
    8, 48, 107] / 255;
position = linspace(0, 1, size(anchors, 1));
colors.sequential = interp1(position, anchors, linspace(0, 1, 128));
end
