function limits = smart_limits(values, anchors, paddingRatio)
%SMART_LIMITS 根据真实数据与阈值生成紧凑且不裁切标记的轴域。

if nargin < 2 || isempty(anchors), anchors = []; end
if nargin < 3 || isempty(paddingRatio), paddingRatio = 0.08; end
assert(paddingRatio >= 0 && paddingRatio <= 0.4, ...
    'paddingRatio must be between 0 and 0.4');
values = [double(values(:)); double(anchors(:))];
values = values(isfinite(values));
assert(~isempty(values), 'smart_limits requires at least one finite value');
lower = min(values);
upper = max(values);
span = upper - lower;
if span <= eps(max(abs(values)))
    span = max(1, abs(lower)) * 0.1;
end
padding = span * paddingRatio;
limits = [lower - padding, upper + padding];
end
