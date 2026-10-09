namespace Shop.Billing;

public class Invoice
{
    public Invoice(int lines) { Prepare(lines); }

    void Prepare(int lines)
    {
        this.Recalculate();
        Rounding.ToCents(lines);
        System.Console.WriteLine(lines);
    }

    public int Recalculate() => Rounding.ToCents(0);

    public static Invoice Create() => new Invoice(1);
}

static class Rounding
{
    public static int ToCents(int value) => value * 100;
}
