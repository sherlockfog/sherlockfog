if exists('b:current_syntax')
	  finish
endif

let s:cpo_save = &cpoptions
set cpoptions&vim

syntax match fogNum /\<\d\+\>/
syntax match fogBuild /build-network/
syntax match fogSetDelay /set-delay/
syntax match fogComment /\#.*/

syntax keyword fogStmt for end connect def run let in do if

highlight default link fogNum Number 
highlight default link fogComment Comment
highlight default link fogBuild Statement
highlight default link fogSetDelay Statement
highlight default link fogStmt Statement

let b:current_syntax = 'fog'

let &cpoptions = s:cpo_save
unlet! s:cpo_save
