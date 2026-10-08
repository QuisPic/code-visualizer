package main

import "fmt"

type Server struct{}

func (s *Server) Start() { s.listen() }
func (s *Server) listen() { fmt.Println("listening") }

func main() {
	s := &Server{}
	s.Start()
}
