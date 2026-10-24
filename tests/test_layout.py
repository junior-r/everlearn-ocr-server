from app.layout import Direction, TextBox, gap, neighbours, rows


def at(text: str, left: float, top: float, width: float = 100, height: float = 30) -> TextBox:
    return TextBox(text, left, top, left + width, top + height)


def test_measures_the_gap_only_in_the_direction_a_box_lies():
    label = at("LABEL", 0, 100)

    assert gap(label, at("right", 130, 105), Direction.RIGHT) == 30
    assert gap(label, at("below", 20, 140), Direction.BELOW) == 10
    assert gap(label, at("above", 20, 60), Direction.ABOVE) == 10
    assert gap(label, at("right", 130, 105), Direction.BELOW) is None
    assert gap(label, at("below", 20, 140), Direction.RIGHT) is None


def test_boxes_that_touch_or_overlap_slightly_are_at_no_distance():
    assert gap(at("a", 0, 0), at("b", 95, 0), Direction.RIGHT) == 0


def test_a_box_on_the_wrong_side_is_not_a_neighbour():
    assert gap(at("a", 200, 0), at("b", 0, 0), Direction.RIGHT) is None


def test_neighbours_are_nearest_first_and_within_reach():
    label = at("LABEL", 0, 0)
    near, far, out_of_reach = at("near", 110, 0), at("far", 160, 0), at("out", 500, 0)

    assert list(neighbours(label, [far, out_of_reach, near, label], Direction.RIGHT)) == [near, far]


def test_lines_below_must_be_closer_than_a_line_height():
    label = at("LABEL", 0, 0)

    assert list(neighbours(label, [at("next", 0, 80)], Direction.BELOW)) == []


def test_groups_boxes_into_lines_read_left_to_right():
    a, b, c, d = at("a", 300, 2), at("b", 0, 0), at("c", 0, 40), at("d", 150, 44)

    assert rows([c, a, d, b]) == [[b, a], [c, d]]
