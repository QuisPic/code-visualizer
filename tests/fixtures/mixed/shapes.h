#pragma once
namespace geo {
struct Shape {
    double area() const;
    double scaled(double k) const { return area() * k; }
};
double total(Shape const *shapes, int n);
}
