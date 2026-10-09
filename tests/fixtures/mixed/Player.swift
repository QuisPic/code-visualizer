struct Track {
    let title: String
}

class Player {
    var queue: [Track] = []

    init(first: Track) {
        enqueue(first)
    }

    func enqueue(_ track: Track) {
        queue.append(track)
        self.refresh()
    }

    private func refresh() {}
}

extension Player {
    func playNext() { refresh() }
}

func startPlayer() -> Player {
    return Player(first: Track(title: "intro"))
}
