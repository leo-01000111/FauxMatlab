# sisotool

Open the Control System Designer panel on a plant: a root locus you drag the closed-loop poles along, with the Bode plot and step response following.

## Syntax

    sisotool
    sisotool(G)
    sisotool(G, C)

## Description

`sisotool(G)` opens the Control System Designer docked beside the analysis workspace, with `G` as the plant. The panel shows three linked plots: the root locus of the compensated loop, the Bode plot of the open loop with its margins, and the closed-loop step response. Dragging a closed-loop pole along the locus sets the compensator gain, and the other two plots follow.

The designer works on the app's shared loop. The sensor block H comes from the analysis workspace, and applying a design writes the compensator into the loop's controller block, so the other tabs show the result straight away.

`sisotool` with no argument opens the designer on the plant G of the current analysis workspace. If the designer is already open, `sisotool(G)` replaces its plant.

`sisotool(G, C)` opens the designer with `C` as the starting compensator: its gain, zeros and poles fill the designer's fields, and the plots show the loop with `C` in it. The designer tunes a gain `K` of 0 or more, so a compensator with a negative gain is refused with an error; move the sign into the plant, `sisotool(-G, -C)`.

The command returns a short description of the request, such as `<sisotool: plant>`. In a script run without the app nothing opens; the request is recorded and the line still runs.

## Example

```matlab
G = zpk([], [0 -2 -5], 10);
rlocus(G)
sisotool(G)
```

## See also

[rlocus](rlocus) · [margin](margin) · [pidtuner](pidtuner) · [ltiview](ltiview) · [lead](lead)
