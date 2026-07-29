function metadata = spatial_axes(ax, xData, yData, zData, unit, azimuth, elevation)
%SPATIAL_AXES 配置等比例正交三维坐标轴，并返回布局报告元数据。

if nargin < 6 || isempty(azimuth), azimuth = 35; end
if nargin < 7 || isempty(elevation), elevation = 25; end
assert(isscalar(azimuth) && isfinite(azimuth), 'azimuth must be finite');
assert(isscalar(elevation) && isfinite(elevation) && abs(elevation) <= 90, ...
    'elevation must be finite and within -90--90 degrees');
unit = strtrim(char(unit));
assert(~isempty(unit), '3D coordinate unit must not be empty');

xLimits = shumoviz.smart_limits(xData, [], 0.08);
yLimits = shumoviz.smart_limits(yData, [], 0.08);
zLimits = shumoviz.smart_limits(zData, [], 0.08);
centers = [mean(xLimits), mean(yLimits), mean(zLimits)];
span = max([diff(xLimits), diff(yLimits), diff(zLimits)]);
if span <= 0, span = 1; end
radius = span / 2;
xlim(ax, centers(1) + [-radius, radius]);
ylim(ax, centers(2) + [-radius, radius]);
zlim(ax, centers(3) + [-radius, radius]);
daspect(ax, [1, 1, 1]);
pbaspect(ax, [1, 1, 1]);
view(ax, azimuth, elevation);
camproj(ax, 'orthographic');
xlabel(ax, sprintf('x (%s)', unit));
ylabel(ax, sprintf('y (%s)', unit));
zlabel(ax, sprintf('z (%s)', unit));
grid(ax, 'on');
box(ax, 'on');

metadata = struct( ...
    'projection', '3d', ...
    'camera_projection', 'orthographic', ...
    'camera_view', struct('azimuth', azimuth, 'elevation', elevation), ...
    'coordinate_unit', unit);
end
