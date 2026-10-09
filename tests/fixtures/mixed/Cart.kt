package shop

class Cart(val owner: String) {
    private val items = mutableListOf<Int>()

    fun addItem(price: Int) {
        items.add(price)
        this.recount()
        Ledger.record(price)
    }

    private fun recount(): Int = items.size
}

fun Cart.checkout() { addItem(0) }

object Ledger {
    fun record(amount: Int) { println(amount) }
}
