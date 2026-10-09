#include "shapes.h"
#include <vector>

namespace geo {
double Shape::area() const { return 1.0; }

/**
 * Sum of the areas of `n` shapes.
 */
double total(Shape const *shapes, int n)
{
    double sum = 0;
    for (int i = 0; i < n; ++i) sum += shapes[i].area();
    std::vector<int> v;
    v.push_back(n);
    return sum;
}
}

int main()
{
    geo::Shape s;
    return (int)geo::total(&s, 1);
}
