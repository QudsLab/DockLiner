// Minimal inline implementation of CodeMirror.defineSimpleMode for the dockerfile mode addon.
// This is a stopgap that provides the API dockerfile.min.js expects. For full simple-mode features,
// replace this file with the official CodeMirror addon/mode/simple.js.
(function(CodeMirror){
  "use strict";
  function ensurePrefix(states){
    var result = {};
    for(var state in states){
      if(states.hasOwnProperty(state)){
        result[state] = states[state].map(function(rule){ return Object.assign({}, rule); });
      }
    }
    return result;
  }
  CodeMirror.defineSimpleMode = function(name, states){
    var prefixedStates = ensurePrefix(states);
    CodeMirror.defineMode(name, function(config){
      return {
        startState: function(){ return { state: "start", regexIndex: 0, stack: [] }; },
        copyState: function(s){ return { state: s.state, regexIndex: s.regexIndex, stack: s.stack.slice() }; },
        token: function(stream, state){
          var rules = prefixedStates[state.state];
          for(var i = 0; i < rules.length; i++){
            var rule = rules[i];
            var matched = false;
            var m;
            if(rule.regex && (m = stream.match(rule.regex, false))){
              stream.match(rule.regex);
              matched = true;
            } else if(rule.sol && stream.sol()){
              matched = true;
            } else if(rule.token === null && !stream.eol()){
              stream.next();
              matched = true;
            }
            if(matched){
              if(rule.next){
                if(rule.pop){
                  state.state = state.stack.pop() || "start";
                } else if(rule.push){
                  state.stack.push(state.state);
                  state.state = rule.next;
                } else {
                  state.state = rule.next;
                }
              }
              var tok = rule.token;
              if(tok === undefined) tok = null;
              return tok;
            }
          }
          if(!stream.eol()) stream.next();
          return null;
        }
      };
    });
  };
})(window.CodeMirror || window.cm);
