/* Generated fields may refresh; text edited by a person stays until explicitly replaced. */
class DraftBuffer {
 constructor(){this.values={};this.generated={title:'',body:''};}
 capture(title,body){this.values={title,body};}
 accept(next){for(const field of ['title','body']){if(this.values[field]===undefined||this.values[field]===this.generated[field])this.values[field]=next[field];}this.generated={title:next.title,body:next.body};return {...this.values};}
 get edited(){return ['title','body'].some(field=>this.values[field]!==undefined&&this.values[field]!==this.generated[field]);}
 reset(){this.values={...this.generated};return {...this.values};}
}
if(typeof module!=='undefined')module.exports=DraftBuffer;
