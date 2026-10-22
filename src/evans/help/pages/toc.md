# toc

Seconds elapsed since the last tic.

## Syntax

    toc
    elapsed = toc

## Description

`toc` with no output prints `Elapsed time is ... seconds.`, with six decimals. `elapsed = toc` returns the time in seconds as a number and prints nothing, so you can store it or format it with [fprintf](fprintf).

`toc` does not stop the stopwatch: each call measures from the same [tic](tic), until `tic` runs again. Without any `tic`, `toc` counts from when the console started.

Evans does not support `toc(t0)` with a timer value from `t0 = tic`; it raises an error.

## Example

```matlab
tic
for k = 1:50
    p = pole(tf(k, [1 2 k]));
end
elapsed = toc;
fprintf('Under 10 s: %d\n', elapsed < 10)
```

## See also

[tic](tic) · [fprintf](fprintf) · [disp](disp)
