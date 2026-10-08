public class App {
    private int run() { return helper(2); }
    private int helper(int x) { return x * 2; }
    public static void main(String[] args) { new App().run(); }
}
